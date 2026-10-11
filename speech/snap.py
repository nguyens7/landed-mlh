"""Callsign snapping: phonetic + digit weighted edit distance against a roster.

Pilots truncate callsigns and ASR garbles digits, so the distance treats
  * a roster character missing from the spoken form as a cheap deletion (0.5),
  * an extra spoken character as a full insertion (1.0),
  * sound-alike substitutions (5/9, M/N, B/D/P/T/V, ...) as 0.6, others as 1.0.
Score = 1 - distance / len(candidate). When the runner-up is within ``margin`` of the
best, the snap is reported as ambiguous (scenario S4); the caller (or ADS-B) breaks the tie.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent
CSV_PATH = ROOT.parent / "eda" / "data" / "helicopters_2026-10-10.csv"

SIM_CALLSIGNS = ["N312LM", "N2646X", "N2464X"]
TAIL_RE = re.compile(r"^N\d{1,5}[A-Z]{0,2}$")

SOUND_ALIKE = [set("59"), set("MN"), set("BDPTVGCE"), set("FS"), set("KJ"), set("IY"), set("38"), set("QU")]
DELETE_COST = 0.5   # roster char the pilot did not say
INSERT_COST = 1.0   # spoken char with no roster counterpart
SOUND_ALIKE_COST = 0.6
SUB_COST = 1.0
MIN_SNAP_SCORE = 0.6
AMBIGUITY_MARGIN = 0.1


def core(callsign: str) -> str:
    """Strip a leading N tail-number prefix: 'N2646X' -> '2646X'; '2646X' unchanged."""
    c = callsign.upper().replace(" ", "")
    return c[1:] if len(c) > 1 and c[0] == "N" and c[1].isdigit() else c


def load_roster(csv_path: Path = CSV_PATH) -> list[str]:
    regs = list(SIM_CALLSIGNS)
    if csv_path.exists():
        with csv_path.open() as f:
            for row in csv.DictReader(f):
                reg = (row.get("reg") or "").strip().upper()
                if TAIL_RE.match(reg) and reg not in regs:
                    regs.append(reg)
    return regs


def _sub_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    for g in SOUND_ALIKE:
        if a in g and b in g:
            return SOUND_ALIKE_COST
    return SUB_COST


def distance(spoken: str, candidate: str) -> float:
    """Weighted edit distance from the spoken string to a roster candidate (both N-stripped)."""
    n, m = len(spoken), len(candidate)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i * INSERT_COST
    for j in range(1, m + 1):
        d[0][j] = j * DELETE_COST
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(
                d[i - 1][j - 1] + _sub_cost(spoken[i - 1], candidate[j - 1]),
                d[i - 1][j] + INSERT_COST,
                d[i][j - 1] + DELETE_COST,
            )
    return d[n][m]


def similarity(spoken: str, candidate: str) -> float:
    s, c = core(spoken), core(candidate)
    if not c:
        return 0.0
    return max(0.0, 1.0 - distance(s, c) / len(c))


@dataclass
class SnapResult:
    snapped_to: str | None
    snap_score: float
    ambiguous_with: list[str] = field(default_factory=list)
    ranked: list[tuple[str, float]] = field(default_factory=list)


def snap(spoken: str | None, roster: list[str] | None = None, *, min_score: float = MIN_SNAP_SCORE,
         margin: float = AMBIGUITY_MARGIN) -> SnapResult:
    """Snap a normalised spoken callsign ('2646X', 'N312LM', '64X') to the roster."""
    if not spoken:
        return SnapResult(None, 0.0)
    roster = roster if roster is not None else load_roster()
    ranked = sorted(((r, similarity(spoken, r)) for r in roster), key=lambda x: (-x[1], x[0]))
    if not ranked or ranked[0][1] < min_score:
        return SnapResult(None, ranked[0][1] if ranked else 0.0, [], ranked[:5])
    top_reg, top_score = ranked[0]
    ambiguous = [r for r, s in ranked[1:] if s >= min_score and top_score - s <= margin]
    return SnapResult(top_reg, round(top_score, 3), ambiguous, ranked[:5])
