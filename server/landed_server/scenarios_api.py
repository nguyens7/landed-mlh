"""Scenario picker endpoints (additive): play a scripted S1-S6 scenario against this server's own pipeline.

    POST /scenario/{id}/play   {start_t?, speed?}   schedules the scenario's pilot lines; returns the timed list
    POST /scenario/reset                            stops playback, clears desk, proposals and the emergency lock
    GET  /scenario/status                           {playing, id}

Lines come from app/public/data/scenarios/<id>/lines.json; the parsed transmission for each line is the pinned
speech result in scenarios/pins/asr_pins.json (so no live ASR). ADS-B positions and the desk roster follow
scenarios/run.py (Desk.sync). Start the server with LANDED_CACHE_DIR=scenarios/server_cache to reuse the curated
template-picker answers. SIMULATION ONLY: fictional registrations, nothing is transmitted.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from landed_agent.models import AdsbPosition, ParsedTransmission
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "app" / "public" / "data" / "scenarios"
PINS_FILE = REPO / "scenarios" / "pins" / "asr_pins.json"
SCENARIO_IDS = ("S1", "S2", "S3A", "S3B", "S4", "S5", "S6")

# Same mapping as scenarios/adapter.py PLACE_MAP: the speech parser's place names to the agent's position ids.
PLACE_MAP = {
    "East 34th": "6N5",
    "Downtown Skyport": "JRB",
    "Brooklyn Bridge": "brooklyn_bridge",
    "Williamsburg Bridge": "williamsburg_bridge",
    "Intrepid": "intrepid",
    "Roosevelt Island": "roosevelt_island_north",
    "Governors Island": "governors_island",
    "Statue of Liberty": "statue_of_liberty",
    "George Washington Bridge": "gwb",
}


class PlayBody(BaseModel):
    start_t: float | None = None  # scenario time the app clock starts at; default: 10 s before the first line
    speed: float = 1.0


# ---------------------------------------------------------------- data


def load_scenario(
    sid: str, data_dir: Path = DATA_DIR, pins_file: Path = PINS_FILE
) -> tuple[dict, list[dict]]:
    """Return (tracks, lines) where each line carries its pinned ParsedTransmission under "parsed"."""
    base = data_dir / sid
    if sid not in SCENARIO_IDS or not (base / "lines.json").exists():
        raise HTTPException(404, f"unknown scenario {sid!r}")
    lines = json.loads((base / "lines.json").read_text())["lines"]
    tracks = json.loads((base / "tracks.json").read_text())
    pins = json.loads(pins_file.read_text()) if pins_file.exists() else {}
    scenario = json.loads((base / "lines.json").read_text()).get("scenario", sid)
    out = []
    for ln in lines:
        pin = pins.get(f"{scenario}/{ln['id']}/{ln['hash']}") or pins.get(f"{sid}/{ln['id']}/{ln['hash']}")
        if pin is None:
            raise HTTPException(500, f"no pinned speech result for {sid}/{ln['id']}")
        parsed = dict(pin["parsed"])
        parsed["slots"] = {
            k: (
                PLACE_MAP.get(v, v)
                if k in ("position", "origin", "destination") and isinstance(v, str)
                else v
            )
            for k, v in (parsed.get("slots") or {}).items()
        }
        out.append({"id": ln["id"], "t": float(ln["t"]), "aircraft": ln["aircraft"], "parsed": parsed})
    out.sort(key=lambda x: x["t"])
    return tracks, out


def position_at(ac: dict, t: float) -> tuple[float, float, float] | None:
    pts = ac["points"]
    if not pts or t < pts[0]["t"] or t > pts[-1]["t"]:
        return None
    for a, b in itertools.pairwise(pts):
        if a["t"] <= t <= b["t"]:
            f = (t - a["t"]) / (b["t"] - a["t"]) if b["t"] > a["t"] else 0.0
            return (
                a["lat"] + (b["lat"] - a["lat"]) * f,
                a["lon"] + (b["lon"] - a["lon"]) * f,
                a["alt_ft_msl"] + (b["alt_ft_msl"] - a["alt_ft_msl"]) * f,
            )
    return None


def squawk_at(ac: dict, t: float) -> str:
    code = "1200"
    for s in sorted(ac.get("squawk", []), key=lambda s: s["t"]):
        if s["t"] <= t:
            code = s["code"]
    return code


def _nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def traffic_for(tracks: dict, reg: str, t: float) -> list[dict]:
    """Nearest non-desk aircraft as the server's TRAFFIC data (port of scenarios/run.py traffic_for)."""
    me = next((a for a in tracks["aircraft"] if a["reg"] == reg), None)
    p0 = position_at(me, t) if me else None
    if me is None or p0 is None:
        return []
    trk = next((p["track_deg"] for p in reversed(me["points"]) if p["t"] <= t), me["points"][0]["track_deg"])
    best = None
    for o in tracks["aircraft"]:
        if o.get("desk", True):
            continue
        p1 = position_at(o, t)
        if p1 is None:
            continue
        d = _nm(p0[0], p0[1], p1[0], p1[1])
        if d <= 6 and (best is None or d < best[0]):
            best = (d, (_bearing(p0[0], p0[1], p1[0], p1[1]) - trk) % 360, p1[2])
    if not best:
        return []
    d, rel, alt = best
    return [
        {
            "clock": round(rel / 30) % 12 or 12,
            "distance_nm": max(0.5, round(d * 2) / 2),
            "traffic_type": "helicopter",
            "altitude_ft": round(alt / 100) * 100,
        }
    ]


# ---------------------------------------------------------------- player


class Player:
    """One scenario playback at a time, driven by wall-clock sleeps scaled by ``speed``."""

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.sid: str | None = None

    @property
    def playing(self) -> bool:
        return self.task is not None and not self.task.done()

    async def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        self.task, self.sid = None, None

    async def run(self, hub: Any, tracks: dict, lines: list[dict], start_t: float, speed: float) -> None:
        roster: list[str] = []
        traffic: list[dict] = []
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        for ln in lines:
            if ln["t"] < start_t:
                continue
            delay = (ln["t"] - start_t) / speed - (loop.time() - t0)
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                reg, t = ln["aircraft"], ln["t"]
                new_traffic = traffic_for(tracks, reg, t)
                has_traffic = any(not a.get("desk", True) for a in tracks["aircraft"])
                if reg not in roster or (new_traffic != traffic and has_traffic):
                    if reg not in roster:
                        roster.append(reg)
                    traffic = new_traffic
                    await hub.set_desk([reg], 29.92, new_traffic, True)
                for a in tracks["aircraft"]:
                    if a["reg"] in roster and (p := position_at(a, t)) is not None:
                        await hub.adsb(
                            AdsbPosition(
                                reg=a["reg"], lat=p[0], lon=p[1], alt_ft=p[2], squawk=squawk_at(a, t)
                            )
                        )
                await hub.transmission(ParsedTransmission.model_validate(ln["parsed"]))
            except Exception:  # one bad line must not stop the demo
                continue


def build_router() -> APIRouter:
    router = APIRouter(prefix="/scenario", tags=["scenario"])
    player = Player()

    def hub_of(request: Request) -> Any:
        return request.app.state.hub

    @router.get("/status")
    async def status():
        return {"playing": player.playing, "id": player.sid}

    @router.post("/reset")
    async def reset(request: Request):
        hub = hub_of(request)
        await player.stop()
        await hub.reset()  # desk (roster, alerts), proposals and the emergency lock (fresh DeskState)
        return {"ok": True, "locked": hub.desk.locked}

    @router.post("/{sid}/play")
    async def play(sid: str, request: Request, body: PlayBody | None = None):
        body = body or PlayBody()
        tracks, lines = load_scenario(sid)
        hub = hub_of(request)
        await player.stop()
        await hub.reset()
        speed = max(0.25, min(32.0, body.speed))
        start_t = body.start_t if body.start_t is not None else max(0.0, (lines[0]["t"] if lines else 0) - 10)
        player.sid = sid
        player.task = asyncio.create_task(player.run(hub, tracks, lines, start_t, speed))
        timed = [
            {
                "id": ln["id"],
                "t": ln["t"],
                "aircraft": ln["aircraft"],
                "in_s": round((ln["t"] - start_t) / speed, 2),
            }
            for ln in lines
            if ln["t"] >= start_t
        ]
        return {"id": sid, "start_t": start_t, "speed": speed, "lines": timed}

    return router
