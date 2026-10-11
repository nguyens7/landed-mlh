"""Expected-vs-actual scoring (pure functions, no I/O).

A ``Check`` compares one expected value with the actual one and ends in a status:

  pass     matches (altitudes within ALT_TOL_FT, strings case/space-insensitive, sets equal)
  partial  some of it matches: a trigger/candidate set that overlaps but is not equal (extra or missing members)
  fail     does not match
  pending  cannot be judged yet, e.g. a server expectation while the server is not reachable ("pending server")

A line/event is ``pass`` only when every non-pending check passes; ``pending`` when nothing failed but some check
is pending; ``partial`` when no check failed outright but at least one is partial; otherwise ``fail``.
A scenario run is "3 out of 3" when every non-pending check passed in each of the repeated runs.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from scn_model import ParseExpect, ResponseExpect

ALT_TOL_FT = 50
PENDING_SERVER = "pending server"
LATENCY_BUDGET_MS = (
    3000  # issue #4: ParsedTransmission in -> agent audio ready under 3 s on the auto tier (ASR is extra)
)


@dataclass
class Check:
    id: str
    field: str
    expected: Any
    actual: Any
    status: str
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def norm(s: Any) -> Any:
    if isinstance(s, str):
        return re.sub(r"\s+", " ", s.strip().lower())
    return s


def contains_all(text: str | None, needles: list[str]) -> tuple[list[str], bool]:
    t = norm(text or "")
    missing = [n for n in needles if norm(n) not in t]
    return missing, not missing


def match_scalar(name: str, expected: Any, actual: Any) -> tuple[str, str]:
    """pass/fail for one value; numeric slots (altitude) use the +-ALT_TOL_FT tolerance."""
    if expected is None:
        return ("pass", "") if actual is None else ("fail", f"expected none, got {actual!r}")
    if actual is None:
        return "fail", "missing"
    if name == "altitude_ft":
        try:
            diff = abs(float(actual) - float(expected))
        except (TypeError, ValueError):
            return "fail", f"not a number: {actual!r}"
        return (
            ("pass", f"within {ALT_TOL_FT} ft (diff {diff:.0f})")
            if diff <= ALT_TOL_FT
            else ("fail", f"diff {diff:.0f} ft")
        )
    return ("pass", "") if norm(expected) == norm(actual) else ("fail", "")


def match_set(expected: list[str], actual: list[str]) -> tuple[str, str]:
    e, a = set(map(norm, expected)), set(map(norm, actual))
    if e == a:
        return "pass", ""
    if e <= a:
        return "partial", f"extra: {sorted(a - e)}"
    if e & a:
        return "partial", f"missing: {sorted(e - a)}"
    return "fail", f"missing: {sorted(e)}"


# ------------------------------------------------------------------ parse side (speech)
def score_parse(prefix: str, exp: ParseExpect, parsed: dict, asr_confidence: float | None) -> list[Check]:
    checks: list[Check] = []

    def add(field_: str, expected: Any, actual: Any, status: str, detail: str = "") -> None:
        checks.append(Check(f"{prefix}.parse.{field_}", field_, expected, actual, status, detail))

    cs = exp.callsign
    if cs is not None:
        pc = parsed.get("callsign", {})
        amb = list(pc.get("ambiguous_with") or [])
        if cs.snapped_to is not None:
            s = "pass" if (pc.get("snapped_to") == cs.snapped_to and not amb) else "fail"
            add(
                "callsign.snapped_to",
                cs.snapped_to,
                pc.get("snapped_to"),
                s,
                f"ambiguous_with={amb}" if amb else "",
            )
        if cs.ambiguous is not None:
            add(
                "callsign.ambiguous", cs.ambiguous, bool(amb), "pass" if bool(amb) == cs.ambiguous else "fail"
            )
        if cs.candidates_include:
            cands = ([pc["snapped_to"]] if pc.get("snapped_to") else []) + amb
            missing = [c for c in cs.candidates_include if c not in cands]
            add(
                "callsign.candidates",
                cs.candidates_include,
                cands,
                "fail" if missing else "pass",
                f"missing {missing}" if missing else "",
            )
    if exp.intent is not None:
        add(
            "intent",
            exp.intent,
            parsed.get("intent"),
            "pass" if parsed.get("intent") == exp.intent else "fail",
        )
    slots = parsed.get("slots", {})
    for k, v in exp.slots.items():
        status, detail = match_scalar(k, v, slots.get(k))
        add(f"slots.{k}", v, slots.get(k), status, detail)
    if exp.emergency is not None:
        add(
            "emergency",
            exp.emergency,
            parsed.get("emergency"),
            "pass" if bool(parsed.get("emergency")) == exp.emergency else "fail",
        )
    if exp.min_asr_confidence is not None:
        ok = asr_confidence is not None and asr_confidence >= exp.min_asr_confidence
        add("asr_confidence>=", exp.min_asr_confidence, asr_confidence, "pass" if ok else "fail")
    if exp.max_asr_confidence is not None:
        ok = asr_confidence is not None and asr_confidence <= exp.max_asr_confidence
        add("asr_confidence<=", exp.max_asr_confidence, asr_confidence, "pass" if ok else "fail")
    return checks


# ------------------------------------------------------------------ response side (server)
def expects_anything(exp: ResponseExpect) -> bool:
    return any([exp.mode, exp.template_id, exp.tier, exp.triggers, exp.spoken_contains, exp.card_contains])


def score_response(
    prefix: str, exp: ResponseExpect, actual: dict | None, latency_ms: float | None = None
) -> list[Check]:
    """``actual`` is the adapter's normalised outcome, or None when no server answered ("pending server")."""
    fields: list[tuple[str, Any]] = []
    if exp.mode:
        fields.append(("mode", exp.mode))
    if exp.template_id:
        fields.append(("template_id", exp.template_id))
    if exp.tier:
        fields.append(("tier", exp.tier))
    if exp.triggers:
        fields.append(("triggers", exp.triggers))
    if exp.spoken_contains:
        fields.append(("spoken_contains", exp.spoken_contains))
    if exp.card_contains:
        fields.append(("card_contains", exp.card_contains))
    checks: list[Check] = []
    for name, expected in fields:
        before = len(checks)
        cid = f"{prefix}.response.{name}"
        if actual is None:
            checks.append(Check(cid, name, expected, None, "pending", PENDING_SERVER))
            continue
        if name in ("mode", "template_id", "tier"):
            a = actual.get(name)
            checks.append(Check(cid, name, expected, a, "pass" if a == expected else "fail"))
        elif name == "triggers":
            status, detail = match_set(expected, actual.get("triggers") or [])
            checks.append(Check(cid, name, expected, actual.get("triggers") or [], status, detail))
        else:
            text = actual.get("spoken_text") if name == "spoken_contains" else actual.get("card_text")
            missing, ok = contains_all(text, expected)
            checks.append(
                Check(
                    cid,
                    name,
                    expected,
                    text,
                    "pass" if ok else "fail",
                    f"missing {missing}" if missing else "",
                )
            )
        if exp.known_gap and (not exp.known_gap_fields or name in exp.known_gap_fields):
            for c in checks[before:]:
                if c.status in ("fail", "partial"):
                    c.status, c.detail = "gap", f"known gap: {exp.known_gap}"
    if exp.tier == "auto" or exp.mode == "speak":
        cid = f"{prefix}.response.latency_ms"
        if actual is None or latency_ms is None:
            checks.append(Check(cid, "latency_ms", f"<={LATENCY_BUDGET_MS}", None, "pending", PENDING_SERVER))
        else:
            checks.append(
                Check(
                    cid,
                    "latency_ms",
                    f"<={LATENCY_BUDGET_MS}",
                    round(latency_ms),
                    "pass" if latency_ms <= LATENCY_BUDGET_MS else "fail",
                    "server round trip: transmission in -> audio ready (ASR and parse reported separately)",
                )
            )
    return checks


def status_of(checks: list[Check]) -> str:
    st = {c.status for c in checks}
    if not checks:
        return "pass"
    if "fail" in st:
        return "fail"
    if "partial" in st:
        return "partial"
    if "pending" in st:
        return "pending"
    if "gap" in st:
        return "gap"
    return "pass"


def tally(checks: list[Check]) -> dict[str, int]:
    out = {"pass": 0, "fail": 0, "partial": 0, "pending": 0, "gap": 0}
    for c in checks:
        out[c.status] += 1
    out["total"] = len(checks)
    return out


@dataclass
class RunScore:
    checks: list[Check] = field(default_factory=list)

    def add(self, more: list[Check]) -> None:
        self.checks.extend(more)

    @property
    def tally(self) -> dict[str, int]:
        return tally(self.checks)

    @property
    def status(self) -> str:
        return status_of(self.checks)

    @property
    def passed_all_judged(self) -> bool:
        """True when nothing failed or partially matched (pending checks are not judged)."""
        t = self.tally
        return t["fail"] == 0 and t["partial"] == 0


def three_of_three(runs: list[list[Check]]) -> dict:
    """Aggregate repeated runs: for each check id, pass count over runs; 3/3 = passed in every run."""
    ids: dict[str, list[str]] = {}
    for run in runs:
        for c in run:
            ids.setdefault(c.id, []).append(c.status)
    per_check = {}
    for cid, sts in ids.items():
        judged = [s for s in sts if s not in ("pending", "gap")]
        per_check[cid] = {
            "passes": sum(s == "pass" for s in judged),
            "runs": len(sts),
            "judged": len(judged),
            "pending": len(sts) - len(judged),
            "gap": sts.count("gap"),
            "stable": len(judged) > 0 and all(s == "pass" for s in judged),
        }
    judged_checks = [v for v in per_check.values() if v["judged"] > 0]
    return {
        "runs": len(runs),
        "checks": per_check,
        "all_judged_passed_every_run": bool(judged_checks)
        and all(v["stable"] and v["judged"] == len(runs) for v in judged_checks),
        "judged": len(judged_checks),
        "pending": sum(1 for v in per_check.values() if v["judged"] == 0),
    }
