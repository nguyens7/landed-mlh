"""Pluggable speech-to-text with an NYC vocabulary prompt and a per-utterance confidence.

Backends (``--asr gemini|openai``):
  * gemini  : ``gemini-3.8-flash`` via generateContent with a response schema. Gemini 3.x does not
              expose token logprobs, so confidence is derived from evidence the model can supply:
                conf_self        = audio_quality * (1 - share of words the model flags as uncertain)
                conf_consistency = mean(1 - WER(primary, resampled transcript)) over 2 temperature-1 resamples
                confidence       = conf_self * conf_consistency
  * openai  : ``gpt-4o-transcribe``, confidence = exp(mean token logprob). Results come from the on-disk
              cache only (the user asked for no further OpenAI spend after the provider switch).
Everything is cached on disk keyed by sha256(audio + model + prompt).
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from normalize import normalize_for_wer, spell_callsign
from snap import SIM_CALLSIGNS, load_roster

GEMINI_ASR_MODEL = "gemini-3.8-flash"   # chosen from the ablation in RESULTS.md (3.5-flash-lite was far worse)
OPENAI_ASR_MODEL = "gpt-4o-transcribe"
RESAMPLES = 2
CACHE_DIR = Path(__file__).parent / ".cache" / "asr"
GEMINI_CACHE_DIR = Path(__file__).parent / ".cache" / "asr_gemini"


def nyc_prompt(include_callsigns: bool = True) -> str:
    roster = load_roster()
    spoken = [f"MEDEVAC {spell_callsign(r[1:])}" for r in SIM_CALLSIGNS]
    spoken += [f"November {spell_callsign(r[1:])}" for r in roster[len(SIM_CALLSIGNS):len(SIM_CALLSIGNS) + 8]]
    callsign_part = ("Callsigns: " + "; ".join(spoken) + ".") if include_callsigns else ""
    return (
        "Helicopter radio call to the Landed helo desk, New York City. Vocabulary: MEDEVAC, Landed desk, "
        "Downtown Skyport, East 34th Street, Intrepid, Brooklyn Bridge, Manhattan Bridge, Williamsburg Bridge, "
        "Roosevelt Island, Statue of Liberty, George Washington Bridge, Hell Gate, Hudson, East River, "
        "LaGuardia, Flushing Hospital, Bellevue, northbound, southbound, IMC, VFR, MAYDAY, PAN-PAN, squawk. "
        "Phonetic alphabet: Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliet Kilo Lima Mike "
        "November Oscar Papa Quebec Romeo Sierra Tango Uniform Victor Whiskey X-Ray Yankee Zulu. "
        + callsign_part
    ).strip()


GENERIC_PROMPT = ("Air traffic control radio communication between pilots and controllers. Callsigns, runway "
                  "numbers, headings, altitudes, flight levels, phonetic alphabet: Alpha Bravo Charlie Delta "
                  "Echo Foxtrot Golf Hotel India Juliet Kilo Lima Mike November Oscar Papa Quebec Romeo Sierra "
                  "Tango Uniform Victor Whiskey X-Ray Yankee Zulu.")


@dataclass
class ASRResult:
    text: str
    confidence: float | None
    min_token_prob: float | None = None
    n_tokens: int = 0
    conf_self: float | None = None
    conf_consistency: float | None = None
    latency_s: float | None = None
    cached: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class CacheMiss(RuntimeError):
    pass


def _key(audio: bytes, model: str, prompt: str) -> str:
    h = hashlib.sha256()
    h.update(audio)
    h.update(model.encode())
    h.update(prompt.encode())
    return h.hexdigest()


# ------------------------------------------------------------------ OpenAI (cache only)
def confidence_from_logprobs(logprobs: list[float]) -> tuple[float | None, float | None]:
    if not logprobs:
        return None, None
    return math.exp(sum(logprobs) / len(logprobs)), math.exp(min(logprobs))


def _transcribe_openai(path: Path, prompt: str, model: str = OPENAI_ASR_MODEL) -> ASRResult:
    cache = CACHE_DIR / f"{_key(path.read_bytes(), model, prompt)}.json"
    if not cache.exists():
        raise CacheMiss(f"OpenAI ASR not cached for {path.name}; no new OpenAI calls are made")
    d = json.loads(cache.read_text())
    return ASRResult(**{**d, "cached": True})


# ------------------------------------------------------------------ Gemini
ASR_INSTRUCTIONS = (
    "Transcribe this radio transmission verbatim. Do not correct, complete or invent words; if a word is "
    "unclear write your best hearing and list it in uncertain_words. If the audio is silent or unintelligible "
    "return an empty transcript. audio_quality is your 0-1 rating of how intelligible the audio is."
)


def _gemini_schema():
    from pydantic import BaseModel, Field

    class Transcript(BaseModel):
        transcript: str
        uncertain_words: list[str] = Field(default_factory=list)
        audio_quality: float = Field(ge=0, le=1)

    return Transcript


def _gemini_call(client, audio: bytes, prompt: str, temperature: float, model: str = GEMINI_ASR_MODEL):
    from google.genai import types

    Transcript = _gemini_schema()
    last: Exception | None = None
    for attempt in range(5):
        try:
            r = client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=audio, mime_type="audio/wav"),
                          f"{ASR_INSTRUCTIONS}\n\nContext and vocabulary: {prompt}"],
                config=types.GenerateContentConfig(
                    temperature=temperature, response_mime_type="application/json",
                    response_schema=Transcript,
                    thinking_config=types.ThinkingConfig(thinking_level="minimal" if "lite" in model else "low"),
                    max_output_tokens=2000))
            if not r.candidates or r.text is None:
                # The model returned nothing (filtered or silent audio): treat as an empty, zero-quality
                # transcript rather than failing the batch; the zero quality score hands it off.
                if attempt >= 1:
                    return Transcript(transcript="", uncertain_words=[], audio_quality=0.0)
                raise RuntimeError("empty ASR response")
            cand = r.candidates[0]
            if str(cand.finish_reason) not in ("FinishReason.STOP", "STOP"):
                raise RuntimeError(f"incomplete ASR output: {cand.finish_reason}")
            return Transcript.model_validate_json(r.text)
        except Exception as e:  # noqa: BLE001 - retry transient API errors, re-raise after 5 tries
            last = e
            print(f"[gemini asr retry {attempt}] {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Gemini ASR failed: {last}")


def _word_agreement(a: str, b: str) -> float:
    import jiwer

    na, nb = normalize_for_wer(a), normalize_for_wer(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return max(0.0, 1.0 - jiwer.wer(na, nb))


def _transcribe_gemini(path: Path, prompt: str, resamples: int = RESAMPLES, model: str = GEMINI_ASR_MODEL) -> ASRResult:
    audio = path.read_bytes()
    cache = GEMINI_CACHE_DIR / f"{_key(audio, model + f'|r{resamples}', prompt)}.json"
    if cache.exists():
        return ASRResult(**{**json.loads(cache.read_text()), "cached": True})

    from keys import gemini_client
    client = gemini_client()
    t0 = time.time()
    first = _gemini_call(client, audio, prompt, 0.0, model)
    latency = time.time() - t0
    words = max(1, len(first.transcript.split()))
    unc = min(len(first.uncertain_words), words) / words
    conf_self = first.audio_quality * (1 - unc) if first.transcript.strip() else 0.0
    agree = [_word_agreement(first.transcript, _gemini_call(client, audio, prompt, 1.0, model).transcript)
             for _ in range(resamples)]
    conf_cons = sum(agree) / len(agree) if agree else None   # resamples=0: self-report only (cheap mode)
    res = ASRResult(text=first.transcript.strip(), confidence=conf_self * (conf_cons if agree else 1.0),
                    conf_self=conf_self,
                    conf_consistency=conf_cons, latency_s=latency)
    GEMINI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(res.to_dict()))
    return res


def transcribe(path: str | Path, prompt: str | None = None, backend: str = "gemini",
               resamples: int = RESAMPLES, model: str = GEMINI_ASR_MODEL) -> ASRResult:
    path = Path(path)
    prompt = nyc_prompt() if prompt is None else prompt
    if backend == "gemini":
        return _transcribe_gemini(path, prompt, resamples, model)
    if backend == "openai":
        return _transcribe_openai(path, prompt)
    raise ValueError(f"unknown ASR backend {backend!r}")
