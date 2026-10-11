"""FastAPI server. The Gemini key lives in this process's environment only and is never sent anywhere else.

Run: server/scripts/with_gemini_key.sh uv run --project server uvicorn landed_server.app:app --port 8787
SIMULATION ONLY: nothing here transmits on a real frequency, and notify-ops is a test-number stub.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from collections.abc import Callable
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from landed_agent.agent import VoiceAgent
from landed_agent.audit import AuditLog
from landed_agent.gemini_agent import ModelCall, gemini_model_call
from landed_agent.models import AdsbPosition, EngineAlert, ParsedTransmission
from landed_agent.policy import PolicyConfig
from landed_agent.router import Router, router_from_env
from landed_agent.templates import render
from landed_agent.tts import TTSEngine
from pydantic import BaseModel

from .hub import DecisionError, Hub
from .scenarios_api import build_router as scenario_router


class DeskBody(BaseModel):
    roster: list[str]
    altimeter_inhg: float | None = None
    traffic: list[dict[str, Any]] | None = None
    merge: bool = False  # add to the roster instead of replacing it


class DecisionBody(BaseModel):
    proposal_id: str
    decision: Literal["approve", "edit", "reject", "human_transmit"]
    slots: dict[str, Any] | None = None
    who: str = "controller"


class WhoBody(BaseModel):
    who: str = "controller"


def prewarm(hub: Hub) -> None:
    """Synthesize the deterministic phrases for the roster so first use is a cache hit."""
    for reg in hub.desk.roster:
        for tid, slots in (
            ("STANDBY_HANDOFF", {"reg": reg}),
            ("CONTROLLER_TAKING_OVER", {"reg": reg}),
            ("REPORT_ACK", {"reg": reg}),
            ("SAY_AGAIN", {"reg": reg, "what": "transmission"}),
        ):
            with contextlib.suppress(Exception):
                hub.tts.speak(render(tid, slots, hub.desk.roster_set))
    for what in ("transmission", "callsign"):
        with contextlib.suppress(Exception):
            hub.tts.speak(render("SAY_AGAIN", {"what": what}, hub.desk.roster_set))


def create_app(
    model_call: ModelCall | None = None,
    tts: TTSEngine | None = None,
    audit: AuditLog | None = None,
    clock: Callable[[], float] = time.time,
    arm_delay_s: float = 1.0,
    cfg: PolicyConfig | None = None,
    router: Router | Literal["env"] | None = "env",
) -> FastAPI:
    hub = Hub(
        VoiceAgent(model_call or gemini_model_call(), cfg, router_from_env() if router == "env" else router),
        tts or TTSEngine(),
        audit or AuditLog(),
        clock=clock,
        arm_delay_s=arm_delay_s,
    )
    app = FastAPI(title="Landed server (simulation)")
    app.state.hub = hub
    app.include_router(scenario_router())
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def fail(e: DecisionError) -> HTTPException:
        return HTTPException(status_code=e.status, detail=e.detail)

    @app.get("/health")
    async def health():
        return {
            "ok": True,
            "simulation": True,
            "locked": hub.desk.locked,
            "key_loaded": bool(os.environ.get("GEMINI_API_KEY")),
            "router": getattr(hub.agent.router, "provider", None),
        }

    @app.get("/state")
    async def state():
        return hub.snapshot()

    @app.post("/desk")
    async def desk(body: DeskBody):
        await hub.set_desk(body.roster, body.altimeter_inhg, body.traffic, body.merge)
        threading.Thread(target=prewarm, args=(hub,), daemon=True).start()
        return {"roster": hub.desk.roster}

    @app.post("/adsb")
    async def adsb(body: AdsbPosition):
        props, ms = await hub.adsb(body)
        return {"proposals": [p.model_dump() for p in props], "latency_ms": ms}

    @app.post("/transmission")
    async def transmission(body: ParsedTransmission):
        props, ms = await hub.transmission(body)
        return {"proposals": [p.model_dump() for p in props], "latency_ms": ms}

    @app.post("/alerts")
    async def alerts(body: list[EngineAlert]):
        props, ms = await hub.alerts(body)
        return {"proposals": [p.model_dump() for p in props], "latency_ms": ms}

    @app.post("/decision")
    async def decision(body: DecisionBody):
        try:
            p = await hub.decide(body.proposal_id, body.decision, body.who, body.slots)
        except DecisionError as e:
            raise fail(e) from e
        return p.model_dump()

    @app.get("/tts/{proposal_id}")
    async def tts_audio(proposal_id: str):
        try:
            audio = await hub.audio(proposal_id)
        except DecisionError as e:
            raise fail(e) from e
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.post("/unlock")
    async def unlock(body: WhoBody):
        await hub.unlock(body.who)
        return {"locked": False}

    @app.post("/rewind")
    async def rewind():
        return {"dropped": await hub.rewind()}

    @app.post("/reset")
    async def reset():
        await hub.reset()
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        hub.subscribers.add(q)
        try:
            await sock.send_json(hub.snapshot())
            while True:
                await sock.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.subscribers.discard(q)

    return app


def default_app() -> FastAPI:
    return create_app()


app = default_app()
