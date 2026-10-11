from __future__ import annotations

import pytest

from landed_agent.desk import DeskState
from landed_agent.models import AdsbPosition, Callsign, ParsedTransmission, Slots

ROSTER = ["N2646X", "N312LM", "N405LP"]


def make_parsed(
    text: str = "Landed desk, MEDEVAC Two Six Four Six X-Ray, Downtown Skyport, lifting, East River northbound, five hundred",
    *,
    reg: str | None = "N2646X",
    asr: float | None = 0.95,
    parse: float = 0.97,
    intent: str = "checkin",
    snap: float = 0.95,
    ambiguous_with: list[str] | None = None,
    emergency: bool = False,
    **slots,
) -> ParsedTransmission:
    slots.setdefault("position", "Downtown Skyport")
    return ParsedTransmission(
        raw_text=text,
        asr_confidence=asr,
        callsign=Callsign(
            spoken="x", normalized=reg, snapped_to=reg, snap_score=snap, ambiguous_with=ambiguous_with or []
        ),
        intent=intent,  # type: ignore[arg-type]
        slots=Slots(**slots),
        emergency=emergency,
        parse_confidence=parse,
        reason="grammar parse",
    )


@pytest.fixture
def desk() -> DeskState:
    d = DeskState(roster=list(ROSTER))
    # ADS-B: N2646X is right at JRB, so the geometric evidence for its check-in is ~1.
    d.positions["N2646X"] = AdsbPosition(reg="N2646X", lat=40.7013, lon=-74.0085, alt_ft=400)
    return d
