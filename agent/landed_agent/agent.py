"""Orchestration: ParsedTransmission / engine Alert / ADS-B squawk -> Proposal(s).

Speech is only ever produced by ``templates.render``. The server owns expiry, approval and TTS.
"""

from __future__ import annotations

import uuid
from typing import Any

from .desk import DeskState
from .gemini_agent import Choice, ModelCall, choose
from .models import AdsbPosition, EngineAlert, ParsedTransmission, Proposal
from .policy import PolicyConfig, PolicyDecision, Trigger, callsign_ambiguous, evaluate, tier_for_rendered
from .router import Router, RouterDecision, combine, router_mode
from .templates import RenderedText, SlotError, TemplateId, render, validate_slots

EXPIRY_MS = 10_000
OPS_TEST_NUMBER = "555-0100"  # test-number stub only; no real call is ever placed


def _id() -> str:
    return uuid.uuid4().hex[:10]


class VoiceAgent:
    def __init__(self, model_call: ModelCall, cfg: PolicyConfig | None = None, router: Router | None = None):
        self.model_call = model_call
        self.cfg = cfg or PolicyConfig()
        self.router = router  # advisory only; can make a decision more cautious, never less

    # -------------------------------------------------------------- transmissions

    def handle_transmission(self, parsed: ParsedTransmission, desk: DeskState, now_ms: int) -> list[Proposal]:
        d = evaluate(parsed, desk, self.cfg)
        self._update_streaks(parsed, desk)
        heard = parsed.raw_text

        if d.tier == "suppressed":
            return [
                Proposal(
                    id=_id(), tier="suppressed", status="suppressed", reg=d.reg, reason=d.reason,
                    heard=heard, triggers=[t.value for t in d.triggers], created_at_ms=now_ms,
                )
            ]  # fmt: skip

        if d.tier == "emergency":
            desk.locked = True
            props = [
                self._speak(
                    d, TemplateId.CONTROLLER_TAKING_OVER, {"reg": d.reg}, desk, now_ms, heard, "policy"
                )
            ]
            props.append(self.notify_ops_proposal(d.reg, d.reason, now_ms))
            return props

        rd = self._route(parsed, desk, d)
        source = "policy"
        template: TemplateId
        slots: dict[str, Any]
        if d.forced_template is not None:
            template = d.forced_template
            slots = self._forced_slots(d)
        else:
            choice: Choice = choose(parsed, desk, d, self.model_call)
            source = choice.source
            if choice.kind == "handoff":
                d = self._to_handoff(d, f"model handed off: {choice.reason}")
                template, slots = TemplateId.STANDBY_HANDOFF, self._forced_slots(d)
            else:
                assert choice.template_id is not None and choice.slots is not None
                template, slots = choice.template_id, choice.slots
                d.evidence.append(f"model ({source}): {choice.reason}")
        return [self._speak(d, template, slots, desk, now_ms, heard, source, rd)]

    def _route(self, parsed: ParsedTransmission, desk: DeskState, d: PolicyDecision) -> RouterDecision | None:
        """Ask the router and apply it one way only: auto -> approval, or auto/approval -> handoff.

        A policy handoff (any hard trigger) is annotated but never changed.
        """
        if self.router is None:
            return None
        rd = self.router.route(parsed, desk)
        tier, why = combine(d.tier, rd, hard_trigger=bool(d.triggers))
        if router_mode() == "shadow":
            # Thresholds are not yet validated on labelled data (#31): record what the router would do,
            # but leave the policy tier unchanged.
            if tier != d.tier:
                why = f"shadow, would be {tier}: {why}"
            d.evidence.append(f"router (shadow): {why}")
            return rd
        d.evidence.append(why)
        if tier == "handoff" and d.tier != "handoff":
            self._to_handoff(d, f"router: {why}")
        elif tier == "approval" and d.tier == "auto":
            d.tier = "approval"
            d.reason = f"Router asks for review ({why})"
        return rd

    def _update_streaks(self, parsed: ParsedTransmission, desk: DeskState) -> None:
        low = parsed.asr_confidence is not None and parsed.asr_confidence < self.cfg.asr_threshold
        desk.low_asr_streak = desk.low_asr_streak + 1 if low else 0
        reg = parsed.callsign.snapped_to if parsed.callsign.snapped_to in desk.roster_set else None
        amb, _ = callsign_ambiguous(parsed, desk, reg, self.cfg)
        desk.ambiguity_streak = desk.ambiguity_streak + 1 if amb else 0

    @staticmethod
    def _forced_slots(d: PolicyDecision) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        if d.reg:
            slots["reg"] = d.reg
        if d.forced_template == TemplateId.SAY_AGAIN:
            slots["what"] = d.say_again_what or "transmission"
        return slots

    @staticmethod
    def _to_handoff(d: PolicyDecision, why: str) -> PolicyDecision:
        d.tier = "handoff"
        d.reason = why
        d.forced_template = TemplateId.STANDBY_HANDOFF
        return d

    def _speak(
        self, d: PolicyDecision, template: TemplateId, slots: dict[str, Any], desk: DeskState,
        now_ms: int, heard: str, source: str, rd: RouterDecision | None = None,
    ) -> Proposal:  # fmt: skip
        try:
            text = render(template, slots, desk.roster_set)
        except SlotError as e:
            # Cannot happen for validated choices; if it does, never guess: standby + human.
            d = self._to_handoff(d, f"slot validation failed: {str(e).splitlines()[0]}")
            template, slots = TemplateId.STANDBY_HANDOFF, ({"reg": d.reg} if d.reg else {})
            text = render(template, slots, desk.roster_set)
        tier = tier_for_rendered(d.tier, text)
        if d.tier == "auto" and tier == "approval":
            d.reason = "Approval-tier content (landing / go-around / emergency services)"
        status = {
            "auto": "auto_spoken",
            "approval": "pending",
            "handoff": "handoff_spoken",
            "emergency": "handoff_spoken",
        }[tier]
        return Proposal(
            id=_id(), tier=tier, status=status, reg=d.reg, template_id=template.value, slots=slots,  # type: ignore[arg-type]
            spoken_text_preview=str(text), confidence=d.confidence, confidence_parts=d.confidence_parts,
            reason=d.reason, evidence=d.evidence, triggers=[t.value for t in d.triggers], heard=heard,
            created_at_ms=now_ms, expires_at_ms=now_ms + EXPIRY_MS if status == "pending" else None, source=source,
            router={**rd.to_dict(), "mode": router_mode()} if rd else None,
        )  # fmt: skip

    # -------------------------------------------------------------- engine alerts

    def handle_alerts(self, alerts: list[EngineAlert], desk: DeskState, now_ms: int) -> list[Proposal]:
        """Replace the active alert set; answer each aircraft's handoff alert once with STANDBY_HANDOFF.

        Engine alert ids are aircraft hexes (one alert per aircraft), so proposals key on the aircraft.
        """
        # forget aircraft whose handoff alert cleared, so a replay rewind can fire it again
        desk.handled_alerts &= {a.aircraft.reg for a in alerts if a.severity == "handoff"}
        desk.handled_cautions &= {a.aircraft.reg for a in alerts if a.severity == "caution"}
        desk.alerts = {a.id: a for a in alerts}
        out: list[Proposal] = []
        handoff_regs = {a.aircraft.reg for a in alerts if a.severity == "handoff"}
        for a in alerts:
            reg = a.aircraft.reg
            if a.severity == "caution" and reg not in handoff_regs:
                p = self._caution_traffic(a, desk, now_ms)
                if p is not None:
                    out.append(p)
                continue
            if a.severity != "handoff" or reg in desk.handled_alerts or reg not in desk.roster_set:
                continue
            desk.handled_alerts.add(reg)
            # The reason is the engine's own text, shown once; the card re-reads the live alert for
            # the countdown. No internal volume ids or repeated callsign in anything shown.
            ev = [f"engine geometry confidence {a.confidence:.2f}"]
            d = PolicyDecision(
                tier="suppressed" if desk.locked else "handoff", reg=reg, triggers=[Trigger.PATH_PROTECTED_VOLUME],
                forced_template=TemplateId.STANDBY_HANDOFF, confidence=a.confidence,
                confidence_parts={"alert": a.confidence},
                reason=a.reason, evidence=ev,
            )  # fmt: skip
            if desk.locked:
                out.append(Proposal(id=_id(), tier="suppressed", status="suppressed", reg=reg, reason=d.reason,
                                    triggers=["path_protected_volume"], evidence=ev, created_at_ms=now_ms))  # fmt: skip
            else:
                out.append(
                    self._speak(d, TemplateId.STANDBY_HANDOFF, {"reg": reg}, desk, now_ms, "", "policy")
                )
        return out

    def _caution_traffic(self, a: EngineAlert, desk: DeskState, now_ms: int) -> Proposal | None:
        """SPEC S3 variant B: a caution alert gets a TRAFFIC call (auto at engine confidence >= 0.8, else a card).

        A caution never produces a handoff. With no traffic data to cite, or while locked, nothing is proposed.
        """
        reg = a.aircraft.reg
        if desk.locked or reg in desk.handled_cautions or reg not in desk.roster_set or not desk.traffic:
            return None
        slots = {"reg": reg, **desk.traffic[0]}
        try:
            validate_slots(TemplateId.TRAFFIC, slots, desk.roster_set)
        except SlotError:
            return None
        desk.handled_cautions.add(reg)
        auto = a.confidence >= self.cfg.auto_confidence
        d = PolicyDecision(
            tier="auto" if auto else "approval", reg=reg, confidence=a.confidence,
            confidence_parts={"alert": a.confidence},
            reason=a.reason if auto else f"{a.reason} (confidence {a.confidence:.2f} < {self.cfg.auto_confidence})",
            evidence=[f"engine caution alert, geometry confidence {a.confidence:.2f}"],
        )  # fmt: skip
        return self._speak(d, TemplateId.TRAFFIC, slots, desk, now_ms, "", "policy")

    # -------------------------------------------------------------- ADS-B squawk

    def handle_adsb(self, pos: AdsbPosition, desk: DeskState, now_ms: int) -> list[Proposal]:
        """Record a position. An emergency squawk is an emergency regardless of what ASR heard."""
        was_emergency = set(desk.emergency_squawkers())
        desk.positions[pos.reg] = pos
        new = [r for r in desk.emergency_squawkers() if r not in was_emergency]
        if not new or desk.locked:
            return []
        reg = new[0]
        desk.locked = True
        d = PolicyDecision(
            tier="emergency", reg=reg, triggers=[Trigger.EMERGENCY], confidence=1.0,
            reason=f"ADS-B squawk {pos.squawk} on {reg}: emergency regardless of voice parse",
            evidence=[f"squawk {pos.squawk}"],
        )  # fmt: skip
        return [
            self._speak(d, TemplateId.CONTROLLER_TAKING_OVER, {"reg": reg}, desk, now_ms, "", "policy"),
            self.notify_ops_proposal(reg, d.reason, now_ms),
        ]

    # -------------------------------------------------------------- notify ops (test-number stub)

    def notify_ops_proposal(self, reg: str | None, why: str, now_ms: int) -> Proposal:
        who = f"MEDEVAC {reg}" if reg else "a helicopter"
        return Proposal(
            id=_id(), kind="notify_ops", tier="approval", status="pending", reg=reg,
            spoken_text_preview=f"SIMULATED call to heliport ops, TEST number {OPS_TEST_NUMBER}: {who} declared an emergency.",
            reason="Optional: notify heliport ops (simulated Vapi call, test number only). " + why,
            triggers=[Trigger.EMERGENCY.value], created_at_ms=now_ms, expires_at_ms=now_ms + EXPIRY_MS,
        )  # fmt: skip


def rendered_preview(template_id: str, slots: dict[str, Any], roster: frozenset[str]) -> RenderedText:
    """Re-render after a human edit (validates slots; raises SlotError)."""
    return render(template_id, slots, roster)
