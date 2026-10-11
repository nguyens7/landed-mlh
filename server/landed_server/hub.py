"""Proposal lifecycle: creation, 10 s expiry (server-enforced), approve / edit / reject, lock, audit, push.

Nothing is audible unless a proposal is ``auto_spoken`` / ``handoff_spoken`` (policy-approved, safe words)
or ``approved`` by a human. An expired proposal is dropped and its audio is never served.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

from landed_agent.agent import EXPIRY_MS, VoiceAgent
from landed_agent.audit import AuditLog
from landed_agent.desk import DeskState
from landed_agent.models import AdsbPosition, EngineAlert, ParsedTransmission, Proposal
from landed_agent.templates import SlotError, render
from landed_agent.tts import TTSEngine

AUDIBLE = {"auto_spoken", "handoff_spoken", "approved"}


class DecisionError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class Hub:
    def __init__(
        self,
        agent: VoiceAgent,
        tts: TTSEngine,
        audit: AuditLog,
        clock: Callable[[], float] = time.time,
        arm_delay_s: float = 1.0,
    ):
        self.agent, self.tts, self.audit, self.clock = agent, tts, audit, clock
        self.arm_delay_ms = int(arm_delay_s * 1000)
        self.desk = DeskState()
        self.proposals: dict[str, Proposal] = {}
        self.order: list[str] = []
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ helpers

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "locked": self.desk.locked,
            "roster": self.desk.roster,
            "proposals": [self.proposals[i].model_dump() for i in self.order],
            "audit": self.audit.read()[-100:],
        }

    def broadcast(self, event: dict[str, Any]) -> None:
        for q in list(self.subscribers):
            q.put_nowait(event)

    def _push(self, p: Proposal) -> None:
        self.broadcast({"type": "proposal", "proposal": p.model_dump()})

    def _log(self, p: Proposal, decision: str, who: str, latency_ms: int | None = None) -> None:
        entry = self.audit.append(p.model_dump(), decision, who, latency_ms)
        self.broadcast({"type": "audit", "entry": entry})

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------------ inputs

    async def set_desk(
        self, roster: list[str], altimeter: float | None, traffic: list[dict] | None, merge: bool = False
    ) -> None:
        async with self._lock:
            names = [*self.desk.roster, *roster] if merge else roster
            self.desk.roster = list(dict.fromkeys(r.upper() for r in names))
            self.desk.handled_alerts.clear()
            if not merge:
                self.desk.handled_cautions.clear()
            self.desk.alerts.clear()
            if altimeter is not None:
                self.desk.altimeter_inhg = altimeter
            if traffic is not None:
                self.desk.traffic = traffic
        self.broadcast({"type": "roster", "roster": self.desk.roster})

    async def transmission(self, parsed: ParsedTransmission) -> tuple[list[Proposal], int]:
        t0 = time.perf_counter()
        async with self._lock:
            props = await asyncio.to_thread(self.agent.handle_transmission, parsed, self.desk, self.now_ms())
        return await self._publish(props, t0)

    async def alerts(self, alerts: list[EngineAlert]) -> tuple[list[Proposal], int]:
        t0 = time.perf_counter()
        async with self._lock:
            props = self.agent.handle_alerts(alerts, self.desk, self.now_ms())
        return await self._publish(props, t0)

    async def adsb(self, pos: AdsbPosition) -> tuple[list[Proposal], int]:
        t0 = time.perf_counter()
        async with self._lock:
            props = self.agent.handle_adsb(pos, self.desk, self.now_ms())
        return await self._publish(props, t0)

    async def _publish(self, props: list[Proposal], t0: float) -> tuple[list[Proposal], int]:
        if any(p.tier == "emergency" for p in props):
            await self._engage_lock(props)
        for p in props:
            self.proposals[p.id] = p
            self.order.append(p.id)
        # audible-by-policy proposals: make the audio first, so latency = transmission in -> audio ready
        await asyncio.gather(*(self._ready_audio(p) for p in props if p.status in AUDIBLE))
        total_ms = round((time.perf_counter() - t0) * 1000)
        for p in props:
            if p.status in AUDIBLE:
                p.latency_ms = total_ms
            self._push(p)
            if p.status == "pending":
                self._spawn(self._expire_later(p.id))
                if p.kind == "speak":
                    self._spawn(self._ready_audio(p, push=True))
            if p.status == "auto_spoken":
                self._log(p, "auto_speak", "agent", total_ms)
            elif p.status == "handoff_spoken":
                self._log(p, "handoff_speak", "agent", total_ms)
            elif p.status == "suppressed":
                self._log(p, "suppressed_by_lock", "agent", total_ms)
            else:
                self._log(p, "proposed", "agent", total_ms)
        return props, total_ms

    async def _ready_audio(self, p: Proposal, push: bool = False) -> None:
        if p.kind != "speak" or not p.template_id:
            return
        text = render(p.template_id, p.slots, self.desk.roster_set)  # re-render: the only source of words
        await asyncio.to_thread(self.tts.speak, text)
        p.audio_ready = True
        if push:
            self._push(p)

    # ------------------------------------------------------------------ lock

    async def _engage_lock(self, new: list[Proposal]) -> None:
        self.desk.locked = True
        for pid in self.order:
            p = self.proposals[pid]
            if p.status == "pending" and p.kind == "speak":
                p.status = "expired"
                self._log(p, "dropped_by_lock", "system")
                self._push(p)
        self.broadcast({"type": "lock", "locked": True})

    async def unlock(self, who: str) -> None:
        self.desk.locked = False
        self.audit.append({"event": "unlock"}, "unlock", who)
        self.broadcast({"type": "lock", "locked": False})

    # ------------------------------------------------------------------ expiry

    async def _expire_later(self, pid: str) -> None:
        p = self.proposals[pid]
        delay = max(0.0, (p.expires_at_ms or 0) / 1000 - self.clock())
        await asyncio.sleep(delay + 0.05)
        self.expire_if_due(pid)

    def expire_if_due(self, pid: str) -> bool:
        p = self.proposals.get(pid)
        if p and p.status == "pending" and p.expires_at_ms is not None and self.now_ms() >= p.expires_at_ms:
            p.status = "expired"  # dropped, never sent
            self._log(p, "expire", "system", self.now_ms() - p.created_at_ms)
            self.broadcast({"type": "expired", "id": pid})
            self._push(p)
            return True
        return False

    # ------------------------------------------------------------------ decisions

    def _pending(self, pid: str) -> Proposal:
        p = self.proposals.get(pid)
        if p is None:
            raise DecisionError(404, "unknown proposal")
        self.expire_if_due(pid)
        if p.status == "expired":
            raise DecisionError(410, "proposal expired and was dropped")
        if p.status != "pending":
            raise DecisionError(409, f"proposal is {p.status}")
        return p

    async def decide(
        self, pid: str, decision: str, who: str, slots: dict[str, Any] | None = None
    ) -> Proposal:
        if decision == "human_transmit":
            p = self.proposals.get(pid) or Proposal(id=pid, tier="suppressed", status="done")
            self._log(p, "human_transmit", who)
            return p
        p = self._pending(pid)
        age = self.now_ms() - p.created_at_ms
        if decision == "reject":
            p.status = "rejected"
            self._log(p, "reject_take_over", who, age)
        elif decision == "approve":
            if age < self.arm_delay_ms:
                raise DecisionError(425, "approval not armed yet (1 s arm delay)")
            if self.desk.locked and p.kind == "speak":
                raise DecisionError(423, "emergency lock: agent transmissions are disabled")
            p.status = "approved" if p.kind == "speak" else "done"
            self._log(p, "approve", who, age)
        elif decision == "edit":
            if p.kind != "speak" or not p.template_id:
                raise DecisionError(422, "only spoken proposals can be edited")
            try:
                text = render(p.template_id, slots or {}, self.desk.roster_set)
            except SlotError as e:
                raise DecisionError(422, str(e).splitlines()[0]) from e
            p.slots, p.spoken_text_preview, p.audio_ready = dict(slots or {}), str(text), False
            p.created_at_ms = self.now_ms()  # re-arm
            p.expires_at_ms = p.created_at_ms + EXPIRY_MS
            self._log(p, "edit", who, age)
            self._spawn(self._ready_audio(p, push=True))
            self._spawn(self._expire_later(p.id))
        else:
            raise DecisionError(422, f"unknown decision {decision!r}")
        self._push(p)
        return p

    # ------------------------------------------------------------------ audio

    async def audio(self, pid: str) -> bytes:
        p = self.proposals.get(pid)
        if p is None:
            raise DecisionError(404, "unknown proposal")
        self.expire_if_due(pid)
        if p.status == "expired":
            raise DecisionError(410, "proposal expired: never spoken")
        if p.status not in AUDIBLE:
            raise DecisionError(409, f"proposal is {p.status}: not cleared to speak")
        if self.desk.locked and p.status == "approved":
            raise DecisionError(423, "emergency lock")
        assert p.template_id
        return await asyncio.to_thread(self.tts.speak, render(p.template_id, p.slots, self.desk.roster_set))

    async def rewind(self) -> int:
        """Replay was seeked: drop pending cards (never sent) and forget answered alerts. Roster, lock and
        the audit log are untouched."""
        n = 0
        for pid in self.order:
            p = self.proposals[pid]
            if p.status == "pending":
                p.status = "expired"
                self._log(p, "dropped_by_rewind", "system")
                self._push(p)
                n += 1
        self.desk.alerts.clear()
        self.desk.handled_alerts.clear()
        self.desk.handled_cautions.clear()
        return n

    async def reset(self) -> None:
        self.desk = DeskState(altimeter_inhg=self.desk.altimeter_inhg)
        self.proposals.clear()
        self.order.clear()
        self.broadcast(self.snapshot())

    async def aclose(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
