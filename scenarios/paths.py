"""Make the sibling ``speech/`` and ``replay/`` packages importable (they use flat, bare-name modules).

Import this module first (``import paths``). ``redirect_speech_caches`` also points the speech package's
on-disk caches and raw TTS audio at ``scenarios/`` so this track never writes outside its own directories.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SPEECH = REPO / "speech"
REPLAY = REPO / "replay"
APP_DATA = REPO / "app" / "public" / "data"
GEO_DIR = APP_DATA / "geo"
OUT_DIR = APP_DATA / "scenarios"
AUDIO_DIR = HERE / "audio"
CACHE_DIR = HERE / ".cache"
PINS_DIR = HERE / "pins"
RESULTS_DIR = HERE / "results"

for _p in (str(REPLAY), str(SPEECH)):
    if _p not in sys.path:
        sys.path.append(_p)


def redirect_speech_caches() -> None:
    """Point the speech modules' module-level cache/audio paths at scenarios/ (idempotent)."""
    import asr
    import parse
    import synth

    synth.SYNTH_DIR = AUDIO_DIR / "tts_raw"
    asr.GEMINI_CACHE_DIR = CACHE_DIR / "asr"
    asr.CACHE_DIR = CACHE_DIR / "asr_openai"
    parse.CACHE_DIR = CACHE_DIR / "llm"
