"""QA-only server factory: real routes/policy, fake template selection and silent WAV audio.

Run on loopback only. This does not test Gemini selection, ASR, or spoken audio quality.
"""

import io
import json
import tempfile
import wave
from pathlib import Path

from landed_agent.audit import AuditLog
from landed_agent.tts import TTSEngine
from landed_server.app import create_app


def choose_template(prompt: str) -> dict:
    data = json.loads(prompt)
    reg = data["aircraft"]
    is_checkin = data["transmission"]["intent"] == "checkin"
    slots = {"reg": reg}
    if is_checkin:
        slots.update(position="JRB", altimeter_inhg=29.92)
    return {
        "name": "choose_template",
        "args": {
            "template_id": "ACK_CHECKIN" if is_checkin else "REPORT_ACK",
            "slots": slots,
            "reason": "QA MOCK: deterministic selection, not a provider result",
        },
    }


def silent_wav(text: str, voice: str, model: str) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 2400)
    return buffer.getvalue()


def make_app():
    directory = Path(tempfile.mkdtemp(prefix="landed-mock-qa-"))
    app = create_app(
        model_call=choose_template,
        tts=TTSEngine(synth=silent_wav, cache_dir=directory / "tts"),
        audit=AuditLog(directory / "audit.jsonl"),
    )
    app.title = "Landed QA ONLY (mocked model and silent audio)"

    @app.get("/qa-mode")
    async def qa_mode():
        return {"mocked_providers": True, "audio": "silence", "simulation": True}

    return app
