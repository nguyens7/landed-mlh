"""Gemini TTS speaking exactly ``render(...)`` output, with a disk cache keyed by (text, voice, model)."""

from __future__ import annotations

import hashlib
import io
import os
import re
import wave
from collections.abc import Callable
from pathlib import Path

from .templates import RenderedText

TTS_MODEL = "gemini-3.8-flash-lite-tts"
# Distinct from the pilot voices Charon / Kore / Fenrir used in speech/synth.py.
AGENT_VOICE = "Aoede"
CACHE_DIR = (
    Path(os.environ.get("LANDED_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache")) / "tts"
)

# (text, voice, model) -> WAV bytes. ``text`` is passed through verbatim: no style prefix, no rewriting.
SynthFn = Callable[[str, str, str], bytes]


def gemini_synth(text: str, voice: str, model: str) -> bytes:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))
        ),
    )
    resp = client.models.generate_content(model=model, contents=text, config=cfg)
    part = resp.candidates[0].content.parts[0].inline_data
    mime = part.mime_type or ""
    m = re.search(r"rate=(\d+)", mime)
    rate = int(m.group(1)) if m else 24000
    if mime.startswith("audio/wav"):
        return part.data
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(part.data)
    return buf.getvalue()


class TTSEngine:
    def __init__(
        self,
        synth: SynthFn = gemini_synth,
        voice: str = AGENT_VOICE,
        model: str = TTS_MODEL,
        cache_dir: Path | None = None,
    ):
        self._synth, self.voice, self.model = synth, voice, model
        self.cache_dir = cache_dir or CACHE_DIR

    def cache_path(self, text: str) -> Path:
        h = hashlib.sha256(f"{text}|{self.voice}|{self.model}".encode()).hexdigest()
        return self.cache_dir / f"{h}.wav"

    def speak(self, text: RenderedText) -> bytes:
        """Audio for ``text``. Accepts only ``RenderedText`` (i.e. output of ``templates.render``)."""
        if not isinstance(text, RenderedText):
            raise TypeError("TTS only speaks RenderedText produced by templates.render()")
        path = self.cache_path(str(text))
        if path.exists():
            return path.read_bytes()
        audio = self._synth(str(text), self.voice, self.model)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return audio
