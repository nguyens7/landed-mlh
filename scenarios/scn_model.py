"""Scenario file schema (pydantic). One YAML file per scenario: s1.yaml ... s6.yaml.

Expectation vocabulary (documented in README.md):
  * template ids : ACK_CHECKIN TRAFFIC CORRIDOR_ENTRY REPORT_ACK SAY_AGAIN STANDBY_HANDOFF CONTROLLER_TAKING_OVER
  * tiers        : auto | approval | handoff
  * modes        : speak (auto transmission) | card (approval card) | handoff (STANDBY_HANDOFF + human card)
                   | silent (agent says nothing) | locked_silent (emergency lock: no transmissions at all)
  * triggers     : the server policy names (agent/landed_agent/policy.py Trigger): path_protected_volume
                   altitude_class_b out_of_whitelist emergency asr_low_twice callsign_ambiguity weather
                   desk_over_capacity low_confidence; plus below_transit_min (SPEC idea, not implemented by the server)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TEMPLATE_IDS = (
    "ACK_CHECKIN",
    "TRAFFIC",
    "CORRIDOR_ENTRY",
    "REPORT_ACK",
    "SAY_AGAIN",
    "STANDBY_HANDOFF",
    "CONTROLLER_TAKING_OVER",
)
TIERS = ("auto", "approval", "handoff")
MODES = ("speak", "card", "handoff", "silent", "locked_silent")
TRIGGERS = (
    "path_protected_volume",
    "altitude_class_b",
    "out_of_whitelist",
    "emergency",
    "asr_low_twice",
    "callsign_ambiguity",
    "weather",
    "desk_over_capacity",
    "low_confidence",
    "below_transit_min",
)
VOICES = ("Charon", "Kore", "Fenrir")
INTENTS = (
    "checkin",
    "position_report",
    "request_route",
    "request_altitude",
    "readback",
    "emergency",
    "unknown",
)
SEVERITIES = ("advisory", "caution", "handoff")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Waypoint(Strict):
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    ref: str | None = Field(None, description="Id from app/public/data/geo/reference_points.geojson")
    hudson_frac: float | None = Field(
        None,
        ge=0,
        le=1,
        description="0 = west edge, 1 = east edge of the Hudson corridor polygon at this latitude",
    )

    @model_validator(mode="after")
    def _located(self) -> Waypoint:
        if self.ref is None and self.lat is None:
            raise ValueError("waypoint needs ref or lat")
        if self.ref is None and self.lon is None and self.hudson_frac is None:
            raise ValueError("waypoint needs lon, hudson_frac or ref")
        return self


class SquawkChange(Strict):
    t: float
    code: str = Field(pattern=r"^\d{4}$")


class AlignEntry(Strict):
    """Shift liftoff so the first entry into a volume (polygon + band) lands at ``t`` (S2: the replay's rule)."""

    volume_prefix: str
    t: float


class SimAircraft(Strict):
    reg: str
    hex: str | None = None
    spoken: str
    type: str = "EC35"
    role: Literal["desk", "traffic"] = "desk"
    role_guess: str = "medevac"
    voice: Literal["Charon", "Kore", "Fenrir"] = "Kore"
    liftoff_t: float = 5.0
    airborne: bool = False  # enters the scene already at cruise altitude and speed (no climb-out)
    cruise_alt_ft: float
    cruise_kt: float
    climb_fpm: float = 800.0
    route: list[Waypoint] = Field(min_length=2)
    squawk: list[SquawkChange] = Field(default_factory=lambda: [SquawkChange(t=0, code="1200")])
    align_entry: AlignEntry | None = None

    @property
    def hex_id(self) -> str:
        return self.hex or f"SIM{self.reg[1:]}"


class CallsignExpect(Strict):
    snapped_to: str | None = None
    ambiguous: bool | None = None
    candidates_include: list[str] = Field(default_factory=list)


class ParseExpect(Strict):
    callsign: CallsignExpect | None = None
    intent: (
        Literal[
            "checkin",
            "position_report",
            "request_route",
            "request_altitude",
            "readback",
            "emergency",
            "unknown",
        ]
        | None
    ) = None
    slots: dict[str, Any] = Field(default_factory=dict)
    emergency: bool | None = None
    min_asr_confidence: float | None = None
    max_asr_confidence: float | None = None


class ResponseExpect(Strict):
    mode: Literal["speak", "card", "handoff", "silent", "locked_silent"] | None = None
    template_id: (
        Literal[
            "ACK_CHECKIN",
            "TRAFFIC",
            "CORRIDOR_ENTRY",
            "REPORT_ACK",
            "SAY_AGAIN",
            "STANDBY_HANDOFF",
            "CONTROLLER_TAKING_OVER",
        ]
        | None
    ) = None
    tier: Literal["auto", "approval", "handoff"] | None = None
    triggers: list[str] = Field(default_factory=list)
    spoken_contains: list[str] = Field(default_factory=list)
    card_contains: list[str] = Field(default_factory=list)
    known_gap: str | None = Field(
        None, description="Server does not implement this yet; a mismatch is reported as a gap, not a failure"
    )
    known_gap_fields: list[str] = Field(
        default_factory=list, description="Limit known_gap to these response fields (empty = all)"
    )

    @model_validator(mode="after")
    def _vocab(self) -> ResponseExpect:
        bad = [t for t in self.triggers if t not in TRIGGERS]
        if bad:
            raise ValueError(f"unknown trigger(s) {bad}; allowed {TRIGGERS}")
        return self


class NearCheck(Strict):
    """Geometry sanity for a pilot line: the speaker must be within ``max_nm`` of ``ref`` at time ``t``."""

    ref: str
    max_nm: float = 0.6


class LineExpect(Strict):
    parse: ParseExpect = Field(default_factory=ParseExpect)
    response: ResponseExpect = Field(default_factory=ResponseExpect)


class Line(Strict):
    id: str
    t: float
    aircraft: str
    text: str
    voice: Literal["Charon", "Kore", "Fenrir"] | None = None
    snr: str = "clean"
    rotor: bool = False
    style: Literal["normal", "urgent"] = "normal"
    near: NearCheck | None = None
    note: str | None = None
    expect: LineExpect = Field(default_factory=LineExpect)

    @model_validator(mode="after")
    def _snr(self) -> Line:
        if self.snr != "clean":
            float(self.snr)
        return self


class Event(Strict):
    """A geometry/engine event derived from the track (not from a pilot line)."""

    id: str
    kind: Literal["engine_alert", "no_alerts", "shoreline", "squawk", "position_match", "desk_count"]
    aircraft: str | None = None
    note: str | None = None
    # engine_alert / shoreline
    volume_prefix: str | None = None
    severity: Literal["advisory", "caution", "handoff"] | None = None
    min_confidence: float | None = None
    lead_s: tuple[float, float] | None = Field(None, description="time_to_entry_s at first sight, [min, max]")
    t_window: tuple[float, float] | None = Field(None, description="first_seen_t must fall in [min, max]")
    # no_alerts
    min_severity: Literal["advisory", "caution", "handoff"] = "advisory"
    # squawk
    code: str | None = None
    # position_match
    at_line: str | None = None
    reported: str | None = None
    min_score: float = 0.9
    # shoreline
    traffic_nm: tuple[float, float] | None = None
    # desk_count
    count: int | None = None
    at_t: float | None = None
    response: ResponseExpect = Field(default_factory=ResponseExpect)


class Summary(Strict):
    transmissions: int | None = None  # every spoken proposal (auto + handoff + takeover)
    auto_transmissions: int | None = None
    handoffs: int | None = None
    cards: int | None = None
    transmissions_after_lock: int | None = None


class GeoExpect(Strict):
    """Route-vs-volume contract validated by tests: every other volume must NOT be entered."""

    must_enter: dict[str, list[str]] = Field(default_factory=dict)  # reg -> volume id prefixes
    may_enter: dict[str, list[str]] = Field(default_factory=dict)  # reg -> extra prefixes tolerated
    corridor_tol_nm: float = 0.35
    corridors: dict[str, list[str]] = Field(
        default_factory=dict
    )  # reg -> corridor ids the track stays within


class Scenario(Strict):
    id: str
    title: str
    spec: str
    summary: str
    window_s: int = Field(description="replay window length in seconds (tracks.json metadata)")
    roster_extra: list[str] = Field(default_factory=list)
    aircraft: list[SimAircraft]
    lines: list[Line]
    events: list[Event] = Field(default_factory=list)
    geo: GeoExpect = Field(default_factory=GeoExpect)
    expected_summary: Summary = Field(default_factory=Summary)

    @model_validator(mode="after")
    def _refs(self) -> Scenario:
        regs = {a.reg for a in self.aircraft}
        for ln in self.lines:
            if ln.aircraft not in regs:
                raise ValueError(f"line {ln.id}: unknown aircraft {ln.aircraft}")
        ids = [ln.id for ln in self.lines] + [e.id for e in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate line/event ids")
        for e in self.events:
            if e.aircraft and e.aircraft not in regs:
                raise ValueError(f"event {e.id}: unknown aircraft {e.aircraft}")
        return self

    @property
    def roster(self) -> list[str]:
        return [a.reg for a in self.aircraft] + list(self.roster_extra)

    def aircraft_by_reg(self, reg: str) -> SimAircraft:
        return next(a for a in self.aircraft if a.reg == reg)


SCENARIO_DIR = Path(__file__).resolve().parent
SCENARIO_IDS = ["S1", "S2", "S3A", "S3B", "S4", "S5", "S6"]


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate(yaml.safe_load(path.read_text()))


def scenario_files() -> list[Path]:
    return sorted(SCENARIO_DIR.glob("s[0-9]*.yaml"))


def load_all() -> dict[str, Scenario]:
    out: dict[str, Scenario] = {}
    for p in scenario_files():
        sc = load_scenario(p)
        out[sc.id] = sc
    return out
