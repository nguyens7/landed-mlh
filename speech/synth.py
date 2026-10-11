"""Synthesize pilot transmissions with TTS and degrade them with a radio channel model.

Primary TTS: Gemini ``gemini-3.8-flash-lite-tts`` (voices Charon, Kore, Fenrir).
Extra voice set: OpenAI ``gpt-4o-mini-tts`` (onyx, nova, ash), generated earlier and kept from cache only
(no new OpenAI calls are made).

Channel: 300-3400 Hz band-pass, compression + soft clipping, AM-style amplitude-faded noise floor at a
target SNR, squelch click/tail, optional rotor bed. Plan: every utterance x 3 voices at "clean"; every
noisy SNR gives each utterance one voice (rotated).

    uv run python synth.py            # synthesize (cached) + render + write manifest.jsonl
"""

from __future__ import annotations

import hashlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfiltfilt

from bank import load_bank

ROOT = Path(__file__).parent
SYNTH_DIR = ROOT / "audio" / "synth"
SR = 16000
GEMINI_TTS_MODEL = "gemini-3.8-flash-lite-tts"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
VOICES = {"gemini": ["Charon", "Kore", "Fenrir"], "openai": ["onyx", "nova", "ash"]}
SNRS: list[str] = ["clean", "20", "10", "5", "0", "-5"]   # 0 and -5 dB probe where recognition breaks


def raw_path(provider: str, item: dict, voice: str) -> Path:
    model = GEMINI_TTS_MODEL if provider == "gemini" else OPENAI_TTS_MODEL
    h = hashlib.sha256(f"{model}|{voice}|{item['style']}|{item['text']}".encode()).hexdigest()[:10]
    if provider == "openai":   # legacy layout from the first (OpenAI) pass
        return SYNTH_DIR / "tts_raw" / f"{item['id']}__{voice}__{h}.wav"
    return SYNTH_DIR / "gemini_raw" / f"{item['id']}__{voice}__{h}.wav"


def _write_pcm(path: Path, wav_bytes: bytes) -> None:
    audio, sr = sf.read(io.BytesIO(wav_bytes))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        audio = resample_poly(audio, SR, sr)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio.astype(np.float32), SR)


def gemini_tts(item: dict, voice: str) -> Path:
    path = raw_path("gemini", item, voice)
    if path.exists():
        return path
    from google.genai import types

    from keys import gemini_client
    client = gemini_client()
    # Style cue in brackets (system instructions are not supported by this TTS model).
    text = f"[urgent, tense] {item['text']}" if item["style"] == "urgent" else item["text"]
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))))
    last: Exception | None = None
    for attempt in range(5):
        try:
            r = client.models.generate_content(model=GEMINI_TTS_MODEL, contents=text, config=cfg)
            data = r.candidates[0].content.parts[0].inline_data.data
            _write_pcm(path, data)
            return path
        except Exception as e:  # noqa: BLE001 - retry transient API errors, re-raise after 5 tries
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Gemini TTS failed for {item['id']}/{voice}: {last}")


def openai_tts_cached(item: dict, voice: str) -> Path:
    path = raw_path("openai", item, voice)
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not cached; no new OpenAI calls are made")
    return path


# ------------------------------------------------------------------ channel model
def _bandpass(x: np.ndarray, lo: float = 300.0, hi: float = 3400.0, sr: int = SR) -> np.ndarray:
    sos = butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x)


def _active_rms(x: np.ndarray) -> float:
    frame = 320
    n = len(x) // frame
    if n == 0:
        return float(np.sqrt(np.mean(x**2)) + 1e-9)
    rms = np.sqrt(np.mean(x[: n * frame].reshape(n, frame) ** 2, axis=1))
    active = rms[rms > rms.max() * 0.1]
    return float(np.sqrt(np.mean(active**2)) + 1e-9)


def _am_noise(n: int, rng: np.random.Generator, sr: int = SR) -> np.ndarray:
    """Band-limited hiss with slow AM fading (carrier-level wobble) and a faint heterodyne whine."""
    hiss = _bandpass(rng.standard_normal(n), sr=sr)
    t = np.arange(n) / sr
    fade = 1.0 + 0.35 * np.sin(2 * np.pi * rng.uniform(0.4, 1.5) * t + rng.uniform(0, 6.28))
    whine = 0.15 * np.sin(2 * np.pi * rng.uniform(900, 1200) * t)
    return hiss * fade + whine * np.std(hiss)


def _rotor_bed(n: int, rng: np.random.Generator, sr: int = SR) -> np.ndarray:
    """Blade-slap harmonics (~21 Hz fundamental) plus turbine whine, amplitude-pulsed."""
    t = np.arange(n) / sr
    f0 = rng.uniform(19, 24)
    x = sum(np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28)) / k**0.7 for k in range(1, 60))
    x = x * (0.6 + 0.4 * np.sin(2 * np.pi * f0 * t))
    x += 0.3 * rng.standard_normal(n)
    return _bandpass(x, 120.0, 3400.0, sr)


def radio_channel(speech: np.ndarray, snr_db: float | None, rotor: bool = False, seed: int = 0,
                  sr: int = SR) -> np.ndarray:
    rng = np.random.default_rng(seed)
    lead, tail = int(0.35 * sr), int(0.35 * sr)
    x = np.concatenate([np.zeros(lead), speech, np.zeros(tail)])
    x = _bandpass(x, sr=sr)
    # compression (soft knee) then soft clipping, as an overdriven transmitter would
    x = x / (np.max(np.abs(x)) + 1e-9)
    x = np.tanh(3.0 * x) / np.tanh(3.0)
    sp_rms = _active_rms(x)
    n = len(x)
    out = x.copy()
    if snr_db is not None:
        noise = _am_noise(n, rng, sr)
        if rotor:
            bed = _rotor_bed(n, rng, sr)
            noise = 0.7 * noise / np.std(noise) + 0.7 * bed / (np.std(bed) + 1e-9)
        noise = noise / (np.sqrt(np.mean(noise**2)) + 1e-9) * sp_rms / (10 ** (snr_db / 20))
        out = out + noise
    # squelch: opening click at start, closing burst after the last speech sample
    click = rng.standard_normal(int(0.012 * sr)) * np.exp(-np.linspace(0, 6, int(0.012 * sr)))
    c0 = lead - int(0.1 * sr)
    out[c0:c0 + len(click)] += 0.8 * sp_rms * 4 * click
    burst = rng.standard_normal(int(0.07 * sr)) * np.exp(-np.linspace(0, 3, int(0.07 * sr)))
    c1 = n - tail + int(0.05 * sr)
    out[c1:c1 + len(burst)] += _bandpass(burst, sr=sr) * sp_rms * 3
    out = out / (np.max(np.abs(out)) + 1e-9) * 0.8
    return out.astype(np.float32)


# ------------------------------------------------------------------ plan + driver
def plan(bank: list[dict], provider: str) -> list[dict]:
    voices_all = VOICES[provider]
    rows = []
    for i, item in enumerate(bank):
        if provider == "openai" and not all(raw_path("openai", item, v).exists() for v in voices_all):
            continue   # script text changed after the OpenAI pass (S2 rewrite); no new OpenAI calls are made
        for snr in SNRS:
            voices = voices_all if snr == "clean" else [voices_all[(i + SNRS.index(snr)) % len(voices_all)]]
            for v in voices:
                rows.append({"item": item, "voice": v, "snr": snr, "provider": provider,
                             "rotor": snr in ("10", "5", "0", "-5") and i % 2 == 1})
    return rows


def render(r: dict) -> dict:
    item, voice, snr, provider = r["item"], r["voice"], r["snr"], r["provider"]
    raw = gemini_tts(item, voice) if provider == "gemini" else openai_tts_cached(item, voice)
    speech, _ = sf.read(raw)
    seed = int(hashlib.sha256(f"{item['id']}{voice}{snr}".encode()).hexdigest()[:8], 16)
    audio = radio_channel(speech, None if snr == "clean" else float(snr), rotor=r["rotor"], seed=seed)
    sub = "" if provider == "openai" else "gemini"   # keep legacy OpenAI paths unchanged
    rel = Path("audio") / "synth" / sub / f"{item['id']}__{voice}__{snr}.wav"
    (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
    sf.write(ROOT / rel, audio, SR)
    return {
        "file": str(rel), "utterance_id": item["id"], "provider": provider, "voice": voice, "snr": snr,
        "rotor": r["rotor"],
        "ground_truth": {"text": item["text"], "scenario": item["scenario"], "callsign": item["callsign"],
                         "intent": item["intent"], "slots": item["slots"], "emergency": item["emergency"]},
    }


def main() -> None:
    bank = load_bank()
    manifest = []
    for provider in ("gemini", "openai"):
        rows = plan(bank, provider)
        if provider == "gemini":   # warm the (cached) TTS raw files concurrently first
            todo = {(r["item"]["id"], r["voice"]): r for r in rows}
            with ThreadPoolExecutor(4) as ex:
                list(ex.map(lambda r: gemini_tts(r["item"], r["voice"]), todo.values()))
        manifest += [render(r) for r in rows]
    (ROOT / "manifest.jsonl").write_text("\n".join(json.dumps(m) for m in manifest) + "\n")
    print(f"{len(bank)} utterances, {len(manifest)} rendered clips -> manifest.jsonl")


if __name__ == "__main__":
    main()
