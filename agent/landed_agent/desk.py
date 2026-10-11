"""Desk state the policy reads: roster (admission order), engine alerts, ADS-B positions, streak counters."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .models import AdsbPosition, EngineAlert
from .templates import POSITIONS

EMERGENCY_SQUAWKS = frozenset({"7700", "7600", "7500"})


def resolve_position(name: str | None) -> str | None:
    """Map a canonical place name (or id) from the parser to a POSITIONS id."""
    if not name:
        return None
    key = _norm(name)
    for pid, (spoken, *_rest) in POSITIONS.items():
        if key in {_norm(pid), _norm(spoken)}:
            return pid
    return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).removeprefix("the ").strip()


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def adsb_match(position_name: str | None, adsb: AdsbPosition | None, tol_nm: float = 1.5) -> float | None:
    """Geometric evidence in [0, 1]: how well the ADS-B track matches the reported place.

    exp(-(d / tol)^2) of the great-circle distance. None when either side is unavailable.
    """
    pid = resolve_position(position_name)
    if pid is None or adsb is None:
        return None
    _, lon, lat, _ = POSITIONS[pid]
    return math.exp(-((distance_nm(adsb.lat, adsb.lon, lat, lon) / tol_nm) ** 2))


@dataclass
class DeskState:
    roster: list[str] = field(default_factory=list)  # admission order; newest last
    alerts: dict[str, EngineAlert] = field(default_factory=dict)
    positions: dict[str, AdsbPosition] = field(default_factory=dict)
    low_asr_streak: int = 0
    ambiguity_streak: int = 0
    locked: bool = False
    altimeter_inhg: float = 29.92
    # Known conflicting/nearby traffic the model may cite in TRAFFIC calls:
    # [{"clock": 3, "distance_nm": 2.0, "traffic_type": "helicopter", "altitude_ft": 700}]
    traffic: list[dict] = field(default_factory=list)
    handled_alerts: set[str] = field(
        default_factory=set
    )  # aircraft regs whose active handoff alert was answered (one per aircraft)
    handled_cautions: set[str] = field(
        default_factory=set
    )  # regs whose caution alert got its TRAFFIC proposal

    @property
    def roster_set(self) -> frozenset[str]:
        return frozenset(self.roster)

    def handoff_alerts(self, reg: str) -> list[EngineAlert]:
        return [a for a in self.alerts.values() if a.aircraft.reg == reg and a.severity == "handoff"]

    def emergency_squawkers(self) -> list[str]:
        return [r for r, p in self.positions.items() if p.squawk in EMERGENCY_SQUAWKS and r in self.roster]
