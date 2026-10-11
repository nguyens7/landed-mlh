"""Thin adapter between the scenario runner and the voice-agent server (server/landed_server/app.py).

THIS IS THE ONLY FILE THAT KNOWS THE SERVER'S WIRE FORMAT. Request shapes follow server/scripts/play_scenario.py.

    GET  /health                  {ok, locked, key_loaded}
    POST /reset                   clear proposals and desk state
    POST /desk                    {roster, altimeter_inhg, traffic, merge}   (clears active alerts: call sparingly)
    POST /adsb                    {reg, lat, lon, alt_ft, squawk}             -> {proposals, latency_ms}
    POST /transmission            ParsedTransmission                          -> {proposals, latency_ms}
    POST /alerts                  [EngineAlert]                               -> {proposals, latency_ms}
    POST /decision                {proposal_id, decision, who, slots?}        -> Proposal
    GET  /tts/{proposal_id}       audio/wav for audible proposals

``normalize`` turns the proposal list into one outcome dict that scoring.py compares with the YAML:
    mode         speak (auto_spoken/approved) | card (pending) | handoff (handoff_spoken, incl. the takeover)
                 | locked_silent (suppressed, or nothing returned while the desk is locked) | silent
    tier         auto | approval | handoff   (the server's "emergency" tier maps to handoff)
    template_id, triggers, spoken_text, card_text (reason + evidence + every proposal's words, including the
    notify-ops stub), proposal_id, source, confidence, extras (the other proposals)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

STATUS_MODE = {
    "auto_spoken": "speak",
    "approved": "speak",
    "pending": "card",
    "handoff_spoken": "handoff",
    "suppressed": "locked_silent",
    "expired": "silent",
    "rejected": "silent",
    "done": "silent",
}
TIER_MAP = {"auto": "auto", "approval": "approval", "handoff": "handoff", "emergency": "handoff"}

# The speech parser's canonical place names differ from the agent's POSITIONS spoken names ("East 34th" vs "East 34th
# Street"), so the agent could not resolve them and skipped its ADS-B cross-check. Send the agent's position ids instead
# (resolve_position accepts ids). Reported to the integrator.
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


@dataclass
class ServerReply:
    ok: bool
    outcome: dict | None
    latency_ms: float | None  # client-measured round trip (includes server TTS when audible)
    server_ms: int | None = None
    raw: Any = None
    error: str | None = None


def normalize(proposals: list[dict], locked: bool = False) -> dict:
    speak = [p for p in proposals if p.get("kind", "speak") == "speak"]
    primary = speak[0] if speak else None
    if primary is None:
        return {
            "mode": "locked_silent" if locked else "silent",
            "template_id": None,
            "tier": None,
            "triggers": [],
            "spoken_text": None,
            "card_text": " ".join(p.get("spoken_text_preview", "") for p in proposals) or None,
            "proposal_id": None,
            "source": None,
            "confidence": None,
            "extras": proposals,
        }
    parts: list[str] = []
    for p in proposals:
        parts += [
            p.get("reason") or "",
            *map(str, p.get("evidence") or []),
            p.get("spoken_text_preview") or "",
        ]
    return {
        "mode": STATUS_MODE.get(primary["status"], "silent"),
        "template_id": primary.get("template_id"),
        "tier": TIER_MAP.get(primary["tier"]),
        "triggers": list(primary.get("triggers") or []),
        "spoken_text": primary.get("spoken_text_preview") or None,
        "card_text": " ".join(x for x in parts if x) or None,
        "proposal_id": primary["id"],
        "source": primary.get("source"),
        "confidence": primary.get("confidence"),
        "extras": [p for p in proposals if p is not primary],
    }


class ServerAdapter:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8787",
        timeout_s: float = 90.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)
        self.context_pushed = False

    # ---------------------------------------------------------------- plumbing
    def health(self) -> dict | None:
        try:
            r = self.client.get("/health")
            return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    def available(self) -> bool:
        return self.health() is not None

    def locked(self) -> bool:
        h = self.health()
        return bool(h and h.get("locked"))

    def _post(self, path: str, body: Any) -> ServerReply:
        t0 = time.perf_counter()
        try:
            r = self.client.post(path, json=body)
        except httpx.HTTPError as e:
            return ServerReply(False, None, None, error=f"{type(e).__name__}: {e}")
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code >= 400:
            return ServerReply(
                False, None, ms, raw=r.text[:500], error=f"HTTP {r.status_code}: {r.text[:200]}"
            )
        try:
            data = r.json() if r.content else None
        except ValueError:
            data = None
        return ServerReply(True, None, ms, raw=data)

    def _proposals(self, rep: ServerReply) -> ServerReply:
        if rep.ok and isinstance(rep.raw, dict):
            rep.server_ms = rep.raw.get("latency_ms")
            rep.outcome = normalize(rep.raw.get("proposals") or [], locked=self.locked())
        return rep

    # ---------------------------------------------------------------- API
    def reset(self) -> bool:
        return self._post("/reset", {}).ok

    def set_desk(
        self,
        roster: list[str],
        altimeter_inhg: float = 29.92,
        traffic: list[dict] | None = None,
        merge: bool = False,
    ) -> bool:
        ok = self._post(
            "/desk",
            {"roster": roster, "altimeter_inhg": altimeter_inhg, "traffic": traffic or [], "merge": merge},
        ).ok
        self.context_pushed = self.context_pushed or ok
        return ok

    def adsb(self, reg: str, lat: float, lon: float, alt_ft: float, squawk: str | None = None) -> ServerReply:
        return self._proposals(
            self._post("/adsb", {"reg": reg, "lat": lat, "lon": lon, "alt_ft": alt_ft, "squawk": squawk})
        )

    def post_transmission(self, parsed: dict) -> ServerReply:
        slots = {
            k: (
                PLACE_MAP.get(v, v)
                if k in ("position", "origin", "destination") and isinstance(v, str)
                else v
            )
            for k, v in (parsed.get("slots") or {}).items()
        }
        return self._proposals(self._post("/transmission", {**parsed, "slots": slots}))

    def post_alerts(self, alerts: list[dict]) -> ServerReply:
        return self._proposals(self._post("/alerts", alerts))

    def decide(
        self, proposal_id: str, decision: str, who: str = "scenario-runner", slots: dict | None = None
    ) -> ServerReply:
        body: dict[str, Any] = {"proposal_id": proposal_id, "decision": decision, "who": who}
        if slots:
            body["slots"] = slots
        return self._post("/decision", body)

    def fetch_tts(self, proposal_id: str) -> bytes | None:
        try:
            r = self.client.get(f"/tts/{proposal_id}")
        except httpx.HTTPError:
            return None
        return r.content if r.status_code == 200 else None
