"""audio -> ASR -> ParsedTransmission for a scenario line, with pinned results for repeatable stage runs.

Modes
  pinned   use the committed pin (scenarios/pins/asr_pins.json) for each line; fall back to live when a line has
           no pin (and say so). No network once every line is pinned. This is the default for demos and tests.
  live     run Gemini ASR on the cached audio (temperature 0 first pass; the consistency resamples used for the
           confidence score run at temperature 1, so ``confidence`` can vary run to run) and the speech parser.
  refresh  live, then write the result to the pin file.

A pin is keyed by scenario/line plus the line's text hash, so editing a line's text, voice or SNR invalidates it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import paths
import scn_audio
from scn_model import Line, Scenario

PINS_FILE = paths.PINS_DIR / "asr_pins.json"


def pin_key(sc: Scenario, ln: Line) -> str:
    return f"{sc.id}/{ln.id}/{scn_audio.text_hash(sc, ln)}"


def load_pins() -> dict:
    return json.loads(PINS_FILE.read_text()) if PINS_FILE.exists() else {}


def save_pins(pins: dict) -> None:
    PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PINS_FILE.write_text(json.dumps(pins, indent=1, sort_keys=True) + "\n")


@dataclass
class Heard:
    text: str
    asr_confidence: float | None
    parsed: dict
    asr_latency_s: float | None
    parse_latency_s: float | None
    source: str  # pinned | live


def live_hear(sc: Scenario, ln: Line, fresh: bool = False) -> Heard:
    """Run ASR + parse. ``fresh`` bypasses the on-disk ASR cache (used by the stability check)."""
    paths.redirect_speech_caches()
    import asr
    import parse

    path = scn_audio.audio_path(sc, ln)
    if not path.exists():
        scn_audio.render_line(sc, ln)
    if fresh:  # ask the model again instead of reading the cache
        key_dir = asr.GEMINI_CACHE_DIR
        original = key_dir
        asr.GEMINI_CACHE_DIR = paths.CACHE_DIR / f"asr_fresh_{time.time_ns()}"
        try:
            res = asr.transcribe(path)
        finally:
            asr.GEMINI_CACHE_DIR = original
    else:
        res = asr.transcribe(path)
    t0 = time.time()
    pt = parse.parse_transmission(res.text, res.confidence, roster=sc.roster, llm=True)
    return Heard(
        text=res.text,
        asr_confidence=res.confidence,
        parsed=pt.model_dump(),
        asr_latency_s=res.latency_s,
        parse_latency_s=round(time.time() - t0, 4),
        source="live",
    )


def hear(
    sc: Scenario, ln: Line, mode: str = "pinned", pins: dict | None = None, fresh: bool = False
) -> Heard:
    pins = pins if pins is not None else load_pins()
    key = pin_key(sc, ln)
    if mode == "pinned" and key in pins:
        p = pins[key]
        return Heard(
            text=p["text"],
            asr_confidence=p["asr_confidence"],
            parsed=p["parsed"],
            asr_latency_s=p.get("asr_latency_s"),
            parse_latency_s=p.get("parse_latency_s"),
            source="pinned",
        )
    h = live_hear(sc, ln, fresh=fresh)
    if mode == "refresh":
        for k in [k for k in pins if k.startswith(f"{sc.id}/{ln.id}/") and k != key]:
            del pins[k]  # drop pins made for an older version of this line
        pins[key] = {
            "text": h.text,
            "asr_confidence": h.asr_confidence,
            "parsed": h.parsed,
            "asr_latency_s": h.asr_latency_s,
            "parse_latency_s": h.parse_latency_s,
            "spoken_text": ln.text,
            "pinned_with": "gemini-3.8-flash ASR + speech/parse.py",
        }
        save_pins(pins)
    return h
