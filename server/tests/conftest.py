from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from landed_agent.audit import AuditLog
from landed_agent.tts import TTSEngine

from landed_server.app import create_app

ROSTER = ["N2646X", "N312LM", "N405LP"]


@pytest.fixture(autouse=True)
def _no_pilot_audio(tmp_path, monkeypatch):
    """Keep the answer lead (pilot clip length) at zero unless a test builds a clip."""
    from landed_server import scenarios_api

    monkeypatch.setattr(scenarios_api, "AUDIO_DIR", tmp_path / "no_audio")

ACK = {
    "template_id": "ACK_CHECKIN",
    "slots": {"reg": "N2646X", "position": "JRB", "altimeter_inhg": 29.92},
    "reason": "routine",
}


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def parsed(text="check in", reg="N2646X", asr=0.95, parse=0.97, intent="checkin", emergency=False, **slots):
    slots.setdefault("position", "Downtown Skyport")
    return {
        "raw_text": text,
        "asr_confidence": asr,
        "callsign": {
            "spoken": "x",
            "normalized": reg,
            "snapped_to": reg,
            "snap_score": 0.95,
            "ambiguous_with": [],
        },
        "intent": intent,
        "slots": slots,
        "emergency": emergency,
        "parse_confidence": parse,
        "parser": "grammar",
        "reason": "fixture",
    }


@pytest.fixture
def spoken() -> list[str]:
    return []


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def client(tmp_path: Path, clock: Clock, spoken: list[str]):
    def synth(text: str, voice: str, model: str) -> bytes:
        spoken.append(text)
        return b"RIFFfake"

    app = create_app(
        model_call=lambda prompt: {"name": "choose_template", "args": ACK},
        tts=TTSEngine(synth=synth, cache_dir=tmp_path / "tts"),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        clock=clock,
        arm_delay_s=1.0,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.app = app  # type: ignore[attr-defined]
        r = await c.post("/desk", json={"roster": ROSTER})
        assert r.status_code == 200
        yield c
    await app.state.hub.aclose()


@pytest.fixture(autouse=True)
def _no_router(monkeypatch):
    """Existing server tests assume no router; router behavior is covered in agent/tests/test_router.py."""
    monkeypatch.setenv("LANDED_ROUTER", "off")
