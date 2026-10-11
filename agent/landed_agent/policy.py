"""Tiering policy (SPEC sections 2 and 2.1). Pure functions: no I/O, no model calls.

Tiers: ``auto`` (routine, conf >= 0.8, no active alert), ``approval`` (0.5 <= conf < 0.8, or approval-tier
content), ``handoff`` (any mandatory trigger, or conf < 0.5), ``emergency`` (speak once, then lock),
``suppressed`` (the emergency lock is on: nothing is spoken).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from .desk import EMERGENCY_SQUAWKS, DeskState, adsb_match, resolve_position
from .models import ParsedTransmission, Tier
from .templates import TemplateId


class Trigger(StrEnum):
    PATH_PROTECTED_VOLUME = "path_protected_volume"
    ALTITUDE_CLASS_B = "altitude_class_b"
    OUT_OF_WHITELIST = "out_of_whitelist"
    EMERGENCY = "emergency"
    ASR_LOW_TWICE = "asr_low_twice"
    CALLSIGN_AMBIGUITY = "callsign_ambiguity"
    WEATHER = "weather"
    BELOW_TRANSIT_MIN = "below_transit_min"
    DESK_OVER_CAPACITY = "desk_over_capacity"
    LOW_CONFIDENCE = "low_confidence"  # tier rule (< 0.5), not one of the eight SPEC triggers


@dataclass(frozen=True)
class PolicyConfig:
    asr_threshold: float = 0.60  # Track C data-backed value (speech/RESULTS.md); configurable
    auto_confidence: float = 0.8
    approval_confidence: float = 0.5
    class_b_floor_ft: int = 1300  # Hudson, SPEC section 2
    class_b_margin_ft: int = 100
    max_helicopters: int = 3
    min_snap_score: float = 0.75  # callsign snap similarity below this counts as ambiguous
    say_again_retries: int = 1  # one SAY_AGAIN before an ambiguity / low-ASR handoff (SPEC S4)
    adsb_tolerance_nm: float = 1.5


EMERGENCY_RE = re.compile(r"\bmay\s?day\b|\bpan[\s-]?pan\b|\bemergency\b|\bdeclaring\b", re.I)


def emergency_gate(text: str) -> bool:
    """ASR-independent keyword gate (issue #16). Runs on the raw transcript only, before any callsign snapping
    or parsing, so a garbled or low-confidence MAYDAY / PAN-PAN still locks the agent. Biased to fire: a false
    lock costs one controller click, a missed emergency costs far more.

    Matches the exact words plus one-edit ASR variants ("maday", "may-day", "pam pam"), including a phrase split
    across two tokens.
    """
    if not text:
        return False
    if EMERGENCY_RE.search(text):
        return True
    toks = re.findall(r"[a-z]+", text.lower())
    cands = [*toks, *(a + b for a, b in pairwise(toks))]
    for c in cands:
        if len(c) >= 5 and _levenshtein(c, "mayday") <= 1:
            return True
        if len(c) >= 5 and _levenshtein(c, "panpan") <= 2:
            return True
        if len(c) >= 8 and _levenshtein(c, "emergency") <= 2:
            return True
    return False


WEATHER_RE = re.compile(
    r"\binadvertent\b|\bimc\b|\blosing visual|\blost visual|\bspecial vfr\b|\bceilings?\b|\bfog\b|\blow visibility\b",
    re.I,
)
OUT_OF_WHITELIST_RE = re.compile(
    r"\bclass (b|bravo)\b|\bpriority\b|\bdirect\b|\bcleared?\b|\brequest(ing)? (to )?(land|landing|clearance|transit)"
    r"|\bcross(ing)?\b.*\b(la ?guardia|lga|final|approach|runway)\b|\bover (the )?(airport|la ?guardia)\b",
    re.I,
)
APPROVAL_CONTENT_RE = re.compile(
    r"\bland(ing)?\b|go.?around|ambulance|emergency services|\bems\b|fire department|police", re.I
)
ROUTINE_INTENTS = frozenset({"checkin", "position_report", "readback"})
REQUEST_INTENTS = frozenset({"request_altitude", "request_route"})
ALTITUDE_RULES = Path(__file__).resolve().parents[2] / "app/public/data/geo/altitude_rules.json"


@lru_cache(maxsize=1)
def hudson_transit_min_ft() -> float | None:
    """Hudson transit minimum from the sourced geo data (14 CFR 93.351/352); None if the file is unavailable."""
    try:
        return float(json.loads(ALTITUDE_RULES.read_text())["rules"]["hudson"]["transit_min_ft_msl"])
    except (OSError, KeyError, ValueError, TypeError):
        return None


@dataclass
class PolicyDecision:
    tier: Tier
    reg: str | None
    triggers: list[Trigger] = field(default_factory=list)
    forced_template: TemplateId | None = None  # set when policy (not the model) picks the words
    say_again_what: str | None = None
    confidence: float = 0.0
    confidence_parts: dict[str, float | None] = field(default_factory=dict)
    reason: str = ""
    evidence: list[str] = field(default_factory=list)


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _digit_perms(reg: str, roster: list[str]) -> list[str]:
    """Other roster callsigns that look like this one: same suffix letters, digits within edit distance 2
    (covers transposed and shifted digits such as N2646X vs N2464X, which the snapper does not flag)."""

    def split(r: str) -> tuple[str, str]:
        body = r.removeprefix("N")
        digits = "".join(c for c in body if c.isdigit())
        return digits, body[len(digits) :]

    d0, s0 = split(reg)
    return [r for r in roster if r != reg and split(r)[1] == s0 and _levenshtein(d0, split(r)[0]) <= 2]


def confidence_parts(
    parsed: ParsedTransmission, desk: DeskState, reg: str | None, cfg: PolicyConfig
) -> tuple[float, dict[str, float | None]]:
    """confidence = ASR x parse x geometric evidence. A missing factor is omitted, never invented."""
    geo = adsb_match(parsed.slots.position, desk.positions.get(reg) if reg else None, cfg.adsb_tolerance_nm)
    parts: dict[str, float | None] = {
        "asr": parsed.asr_confidence,
        "parse": parsed.parse_confidence,
        "geometry": geo,
    }
    conf = 1.0
    for v in parts.values():
        if v is not None:
            conf *= v
    return round(conf, 4), parts


def evaluate(parsed: ParsedTransmission, desk: DeskState, cfg: PolicyConfig | None = None) -> PolicyDecision:
    cfg = cfg or PolicyConfig()
    snapped = parsed.callsign.snapped_to
    reg = snapped if snapped in desk.roster_set else None
    text = parsed.raw_text
    evidence: list[str] = []
    triggers: list[Trigger] = []

    # --- emergency first: it overrides everything, including a parse that lost the word MAYDAY
    squawkers = desk.emergency_squawkers()
    emergency = (
        parsed.emergency
        or parsed.intent == "emergency"
        or emergency_gate(text)
        or parsed.slots.squawk in EMERGENCY_SQUAWKS
        or bool(squawkers)
    )
    if emergency:
        why = "Emergency declared or squawk 7700/7600/7500"
        if squawkers:
            why += f" (ADS-B squawk on {', '.join(squawkers)})"
        tier: Tier = "suppressed" if desk.locked else "emergency"
        return PolicyDecision(
            tier=tier,
            reg=reg or (squawkers[0] if squawkers else None),
            triggers=[Trigger.EMERGENCY],
            forced_template=None if desk.locked else TemplateId.CONTROLLER_TAKING_OVER,
            confidence=1.0,
            reason=why + ". Agent speaks once and then locks silent; the controller owns the frequency.",
            evidence=[f"heard: {text!r}"],
        )
    if desk.locked:
        return PolicyDecision(tier="suppressed", reg=reg, reason="Emergency lock active: agent is silent.")

    # --- 1. projected path intersects a protected volume (engine Alert, severity handoff)
    if reg:
        for a in desk.handoff_alerts(reg):
            triggers.append(Trigger.PATH_PROTECTED_VOLUME)
            evidence.append(
                f"engine alert {a.id}: {a.reason} (conf {a.confidence:.2f}, {a.time_to_entry_s:.0f}s)"
            )
            break

    # --- 2. altitude at or above Class B floor - 100 ft
    limit = cfg.class_b_floor_ft - cfg.class_b_margin_ft
    adsb_alt = desk.positions[reg].alt_ft if reg and reg in desk.positions else None
    for label, alt in (("reported", parsed.slots.altitude_ft), ("ADS-B", adsb_alt)):
        if alt is not None and alt >= limit:
            triggers.append(Trigger.ALTITUDE_CLASS_B)
            evidence.append(
                f"{label} altitude {alt:.0f} ft >= Class B floor {cfg.class_b_floor_ft} - {cfg.class_b_margin_ft}"
            )
            break

    # --- 3. a request outside the whitelist
    if parsed.intent not in ROUTINE_INTENTS or OUT_OF_WHITELIST_RE.search(text):
        triggers.append(Trigger.OUT_OF_WHITELIST)
        evidence.append(f"intent {parsed.intent!r} / request outside the phrase whitelist")

    # --- 5. ASR confidence below threshold twice (first time: ask to say again)
    low_asr = parsed.asr_confidence is not None and parsed.asr_confidence < cfg.asr_threshold
    asr_retry = False
    if low_asr:
        if desk.low_asr_streak >= cfg.say_again_retries:
            triggers.append(Trigger.ASR_LOW_TWICE)
            evidence.append(
                f"ASR {parsed.asr_confidence:.2f} < {cfg.asr_threshold} on {desk.low_asr_streak + 1} consecutive calls"
            )
        else:
            asr_retry = True
            evidence.append(f"ASR {parsed.asr_confidence:.2f} < {cfg.asr_threshold}: asking to say again")

    # --- 6. callsign ambiguity (includes transposed-digit callsigns, cross-checked against ADS-B)
    ambiguous, amb_evidence = callsign_ambiguous(parsed, desk, reg, cfg)
    evidence.extend(amb_evidence)
    amb_retry = False
    if ambiguous:
        if desk.ambiguity_streak >= cfg.say_again_retries:
            triggers.append(Trigger.CALLSIGN_AMBIGUITY)
        else:
            amb_retry = True

    # --- 7a. Hudson transit request below the transit minimum (read from the geo data, never hardcoded)
    t_min = hudson_transit_min_ft()
    alt = parsed.slots.altitude_ft
    if (
        t_min is not None
        and parsed.slots.corridor == "Hudson"
        and parsed.intent in REQUEST_INTENTS
        and alt is not None
        and alt < t_min
    ):
        triggers.append(Trigger.BELOW_TRANSIT_MIN)
        evidence.append(f"requested altitude {alt} ft is below the Hudson transit minimum {t_min:.0f} ft")

    # --- 7. weather / IMC phrases
    if parsed.slots.weather_phrase or WEATHER_RE.search(text):
        triggers.append(Trigger.WEATHER)
        evidence.append(
            f"weather phrase: {parsed.slots.weather_phrase or WEATHER_RE.search(text).group(0)!r}"
        )

    # --- 8. more than 3 helicopters on the desk: the newest beyond the cap is handed off
    if reg and len(desk.roster) > cfg.max_helicopters and desk.roster.index(reg) >= cfg.max_helicopters:
        triggers.append(Trigger.DESK_OVER_CAPACITY)
        evidence.append(f"{len(desk.roster)} helicopters on the desk (cap {cfg.max_helicopters})")

    conf, parts = confidence_parts(parsed, desk, reg, cfg)
    if parsed.reason:
        evidence.insert(0, f"parse: {parsed.reason}")
    # a handoff card reports confidence in the finding, not in the words
    alert_conf = max((a.confidence for a in desk.handoff_alerts(reg)), default=None) if reg else None

    if triggers:
        names = ", ".join(t.value for t in dict.fromkeys(triggers))
        return PolicyDecision(
            tier="handoff",
            reg=reg,
            triggers=list(dict.fromkeys(triggers)),
            forced_template=TemplateId.STANDBY_HANDOFF,
            confidence=alert_conf if alert_conf is not None else conf,
            confidence_parts=parts,
            reason=f"Mandatory handoff: {names}. "
            + "; ".join(e for e in evidence if not e.startswith("parse:"))[:300],
            evidence=evidence,
        )
    if asr_retry or amb_retry:
        return PolicyDecision(
            tier="auto",
            reg=None if amb_retry else reg,
            forced_template=TemplateId.SAY_AGAIN,
            say_again_what="callsign" if amb_retry else "transmission",
            confidence=conf,
            confidence_parts=parts,
            reason="Could not trust the callsign" if amb_retry else "Low ASR confidence",
            evidence=evidence,
        )
    if conf < cfg.approval_confidence:
        return PolicyDecision(
            tier="handoff",
            reg=reg,
            triggers=[Trigger.LOW_CONFIDENCE],
            forced_template=TemplateId.STANDBY_HANDOFF,
            confidence=conf,
            confidence_parts=parts,
            reason=f"Confidence {conf:.2f} < {cfg.approval_confidence}: handing to the controller.",
            evidence=evidence,
        )
    if conf < cfg.auto_confidence or desk.alerts:
        why = (
            f"Confidence {conf:.2f} is in the approval band"
            if conf < cfg.auto_confidence
            else f"{len(desk.alerts)} active alert(s) on the desk"
        )
        return PolicyDecision(
            tier="approval", reg=reg, confidence=conf, confidence_parts=parts, reason=why, evidence=evidence
        )
    return PolicyDecision(
        tier="auto",
        reg=reg,
        confidence=conf,
        confidence_parts=parts,
        reason=f"Routine, confidence {conf:.2f}, no active alert",
        evidence=evidence,
    )


def callsign_ambiguous(
    parsed: ParsedTransmission, desk: DeskState, reg: str | None, cfg: PolicyConfig
) -> tuple[bool, list[str]]:
    cs = parsed.callsign
    if reg is None:
        return True, [f"callsign {cs.spoken or cs.normalized or '?'!r} did not resolve to a roster aircraft"]
    if cs.ambiguous_with:
        cands = list(dict.fromkeys([*([reg] if reg else []), *cs.ambiguous_with]))
        return True, [
            f"callsign ambiguous with {', '.join(cs.ambiguous_with)}",
            _adsb_hint(parsed, desk, cands, cfg),
        ]
    if cs.snap_score < cfg.min_snap_score:
        return True, [f"callsign snap score {cs.snap_score:.2f} < {cfg.min_snap_score}"]
    perms = _digit_perms(reg, desk.roster)
    if not perms:
        return False, []
    # Transposed digits (2646X vs 2464X) are not flagged by the snapper: require an ADS-B cross-check.
    pid = resolve_position(parsed.slots.position)
    matches: dict[str, float | None] = {
        r: adsb_match(parsed.slots.position, desk.positions.get(r), cfg.adsb_tolerance_nm)
        for r in [reg, *perms]
    }
    mine = matches[reg]
    others = [v for r, v in matches.items() if r != reg]
    # every look-alike callsign must have an ADS-B fix too, otherwise we cannot rule it out
    if pid and mine is not None and mine >= 0.5 and all(o is not None and mine >= 2 * o for o in others):
        return False, [
            f"ADS-B position cross-check supports {reg} (match {mine:.2f}) over {', '.join(perms)}"
        ]
    return True, [f"{reg} is a digit permutation of {', '.join(perms)}; ADS-B cross-check inconclusive"]


def _adsb_hint(parsed: ParsedTransmission, desk: DeskState, cands: list[str], cfg: PolicyConfig) -> str:
    """One evidence line for an ambiguous callsign: which candidate the ADS-B position favours (SPEC S4)."""
    scores = {
        r: adsb_match(parsed.slots.position, desk.positions.get(r), cfg.adsb_tolerance_nm) for r in cands
    }
    known = {r: v for r, v in scores.items() if v is not None}
    if not known:
        return "no ADS-B position match available for the candidates, unconfirmed by voice"
    best = max(known, key=lambda r: known[r])
    others = [v for r, v in scores.items() if r != best]
    if known[best] >= 0.5 and all(o is not None and known[best] >= 2 * o for o in others):
        return f"likely {best} (ADS-B position match {known[best]:.1f}), unconfirmed by voice"
    return "ADS-B position match inconclusive: " + ", ".join(f"{r} {v:.1f}" for r, v in known.items())


def tier_for_rendered(decision_tier: Tier, text: str) -> Tier:
    """Approval-tier content rule: anything mentioning landing, go-around or emergency services needs a click."""
    if decision_tier == "auto" and APPROVAL_CONTENT_RE.search(text):
        return "approval"
    return decision_tier
