"""Pilot audio for scenario lines: Gemini TTS (cached) + the radio channel filter from speech/synth.py.

Audio lands in ``scenarios/audio/`` (gitignored). ``manifest.json`` (committed) holds one sha256 per line over
(tts model, voice, style, text, snr, rotor) so audio can be regenerated and drift is detectable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import paths
from scn_model import Line, Scenario

AUDIO_SUBDIR = "lines"


def line_voice(sc: Scenario, ln: Line) -> str:
    return ln.voice or sc.aircraft_by_reg(ln.aircraft).voice


def tts_item(sc: Scenario, ln: Line) -> dict:
    return {"id": f"{sc.id.lower()}_{ln.id.lower()}", "style": ln.style, "text": ln.text}


def text_hash(sc: Scenario, ln: Line) -> str:
    import synth

    key = "|".join([synth.GEMINI_TTS_MODEL, line_voice(sc, ln), ln.style, ln.text, ln.snr, str(ln.rotor)])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def audio_rel(sc: Scenario, ln: Line) -> str:
    return f"{AUDIO_SUBDIR}/{sc.id.lower()}_{ln.id.lower()}__{line_voice(sc, ln)}__{ln.snr}.wav"


def audio_path(sc: Scenario, ln: Line) -> Path:
    return paths.AUDIO_DIR / audio_rel(sc, ln)


def render_line(sc: Scenario, ln: Line) -> Path:
    """Synthesize (cached raw TTS) and degrade one line; deterministic for a given raw clip."""
    import soundfile as sf
    import synth

    paths.redirect_speech_caches()
    voice = line_voice(sc, ln)
    raw = synth.gemini_tts(tts_item(sc, ln), voice)
    speech, _ = sf.read(raw)
    seed = int(hashlib.sha256(f"{sc.id}{ln.id}{voice}{ln.snr}".encode()).hexdigest()[:8], 16)
    audio = synth.radio_channel(
        speech, None if ln.snr == "clean" else float(ln.snr), rotor=ln.rotor, seed=seed
    )
    out = audio_path(sc, ln)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, audio, synth.SR)
    return out


def manifest_entry(sc: Scenario, ln: Line) -> dict:
    return {
        "scenario": sc.id,
        "line": ln.id,
        "aircraft": ln.aircraft,
        "voice": line_voice(sc, ln),
        "snr": ln.snr,
        "rotor": ln.rotor,
        "style": ln.style,
        "text": ln.text,
        "hash": text_hash(sc, ln),
        "audio": f"audio/{audio_rel(sc, ln)}",
    }


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}
