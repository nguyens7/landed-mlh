"""Phrase whitelist (SPEC section 2). ``render`` is the ONLY way to produce spoken text.

Every template has a typed slot model with ``extra="forbid"``. Callsigns are validated against the desk
roster; corridor / direction / clock / reporting point are enums; altitude and distance are ranges.
Nothing here can express a clearance, a runway or approach instruction, or an altitude/heading assignment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class TemplateId(StrEnum):
    ACK_CHECKIN = "ACK_CHECKIN"
    TRAFFIC = "TRAFFIC"
    CORRIDOR_ENTRY = "CORRIDOR_ENTRY"
    REPORT_ACK = "REPORT_ACK"
    SAY_AGAIN = "SAY_AGAIN"
    STANDBY_HANDOFF = "STANDBY_HANDOFF"
    CONTROLLER_TAKING_OVER = "CONTROLLER_TAKING_OVER"


# Templates the model may choose (via choose_template). The last two are issued by policy code only.
MODEL_SELECTABLE = (
    TemplateId.ACK_CHECKIN,
    TemplateId.TRAFFIC,
    TemplateId.CORRIDOR_ENTRY,
    TemplateId.REPORT_ACK,
    TemplateId.SAY_AGAIN,
)

# Reference points on the desk: id -> (spoken name, lon, lat, corridor or None). Coordinates mirror
# app/public/data/geo/reference_points.geojson (a test checks they stay in sync).
POSITIONS: dict[str, tuple[str, float, float, str | None]] = {
    "6N5": ("East 34th Street", -73.972122, 40.742447, None),
    "JRB": ("Downtown Skyport", -74.009028, 40.701214, None),
    "NJ87": ("Newark University Hospital", -74.190842, 40.740847, None),
    "NY52": ("Staten Island University Hospital", -74.083261, 40.584203, None),
    "alpine_tower": ("Alpine Tower", -73.928, 40.954, "Hudson"),
    "gwb": ("George Washington Bridge", -73.9527, 40.8517, "Hudson"),
    "intrepid": ("the Intrepid", -74.0006, 40.7642, "Hudson"),
    "clock": ("Colgate Clock", -74.0343, 40.7179, "Hudson"),
    "statue_of_liberty": ("Statue of Liberty", -74.0445, 40.6892, "Hudson"),
    "vz": ("Verrazzano Bridge", -74.0442, 40.6065, "Hudson"),
    "williamsburg_bridge": ("Williamsburg Bridge", -73.9718, 40.7132, "East River"),
    "governors_island": ("Governors Island", -74.0164, 40.6895, "East River"),
    "brooklyn_bridge": ("Brooklyn Bridge", -73.9969, 40.7061, "East River"),
    "roosevelt_island_north": ("Roosevelt Island north tip", -73.9465, 40.7714, "East River"),
}
PositionId = Literal[
    "6N5", "JRB", "NJ87", "NY52", "alpine_tower", "gwb", "intrepid", "clock", "statue_of_liberty", "vz",
    "williamsburg_bridge", "governors_island", "brooklyn_bridge", "roosevelt_island_north",
]  # fmt: skip

_DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "niner"]
_PHONETIC = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo", "F": "Foxtrot", "G": "Golf",
    "H": "Hotel", "I": "India", "J": "Juliet", "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November",
    "O": "Oscar", "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango", "U": "Uniform",
    "V": "Victor", "W": "Whiskey", "X": "X-Ray", "Y": "Yankee", "Z": "Zulu",
}  # fmt: skip
_CLOCK = {i: _DIGITS[i] for i in range(1, 10)} | {10: "ten", 11: "eleven", 12: "twelve"}
_REG_RE = re.compile(r"^N?[0-9]{1,4}[A-Z]{0,2}$")


def spoken_reg(reg: str) -> str:
    """'N312LM' -> 'Three One Two Lima Mike' (leading N dropped, as in SPEC S1)."""
    body = reg.upper()
    if body.startswith("N") and len(body) > 1:
        body = body[1:]
    out = [_DIGITS[int(c)].capitalize() if c.isdigit() else _PHONETIC[c] for c in body]
    return " ".join(out)


def _digits_words(s: str) -> str:
    return " ".join("point" if c == "." else _DIGITS[int(c)] for c in s)


def spoken_altitude(ft: int) -> str:
    thousands, hundreds = divmod(ft, 1000)
    parts = []
    if thousands:
        parts.append(f"{_DIGITS[thousands]} thousand")
    if hundreds:
        parts.append(f"{_DIGITS[hundreds // 100]} hundred")
    return " ".join(parts) or "zero"


# ------------------------------------------------------------------ slot models


class _Slots(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _RegSlots(_Slots):
    reg: str

    @field_validator("reg")
    @classmethod
    def _reg_shape(cls, v: str) -> str:
        v = v.strip().upper()
        if not _REG_RE.match(v):
            raise ValueError(f"not a valid registration: {v!r}")
        return v


class AckCheckinSlots(_RegSlots):
    position: PositionId
    altimeter_inhg: float = Field(ge=28.0, le=31.0)
    report_point: PositionId | None = None


class TrafficSlots(_RegSlots):
    clock: int = Field(ge=1, le=12)
    distance_nm: float = Field(ge=0.5, le=15.0)
    traffic_type: Literal["helicopter", "airplane", "jet"]
    altitude_ft: int = Field(ge=0, le=3000, multiple_of=100)


class CorridorEntrySlots(_RegSlots):
    corridor: Literal["Hudson", "East River"]
    direction: Literal["north", "south"]
    reporting_point: PositionId

    @model_validator(mode="after")
    def _point_on_corridor(self) -> CorridorEntrySlots:
        if POSITIONS[self.reporting_point][3] != self.corridor:
            raise ValueError(f"{self.reporting_point} is not a {self.corridor} reporting point")
        return self


class ReportAckSlots(_RegSlots):
    pass


class _OptRegSlots(_Slots):
    reg: str | None = None

    @field_validator("reg")
    @classmethod
    def _reg_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if not _REG_RE.match(v):
            raise ValueError(f"not a valid registration: {v!r}")
        return v


class SayAgainSlots(_OptRegSlots):
    what: Literal["transmission", "callsign"] = "transmission"


class StandbyHandoffSlots(_OptRegSlots):
    pass


class ControllerTakingOverSlots(_OptRegSlots):
    pass


@dataclass(frozen=True)
class Template:
    id: TemplateId
    slots_model: type[BaseModel]
    routine: bool  # eligible for the auto tier
    needs_reg: bool


TEMPLATES: dict[TemplateId, Template] = {
    TemplateId.ACK_CHECKIN: Template(TemplateId.ACK_CHECKIN, AckCheckinSlots, True, True),
    TemplateId.TRAFFIC: Template(TemplateId.TRAFFIC, TrafficSlots, True, True),
    TemplateId.CORRIDOR_ENTRY: Template(TemplateId.CORRIDOR_ENTRY, CorridorEntrySlots, True, True),
    TemplateId.REPORT_ACK: Template(TemplateId.REPORT_ACK, ReportAckSlots, True, True),
    TemplateId.SAY_AGAIN: Template(TemplateId.SAY_AGAIN, SayAgainSlots, True, False),
    TemplateId.STANDBY_HANDOFF: Template(TemplateId.STANDBY_HANDOFF, StandbyHandoffSlots, False, False),
    TemplateId.CONTROLLER_TAKING_OVER: Template(
        TemplateId.CONTROLLER_TAKING_OVER, ControllerTakingOverSlots, False, False
    ),
}


class SlotError(ValueError):
    """Slots failed validation. Callers fall back to SAY_AGAIN or handoff."""


class RenderedText(str):
    """Spoken text. Only ``render`` may construct one; TTS accepts nothing else."""

    __slots__ = ()
    _token = object()

    def __new__(cls, value: str, *, _token: object = None) -> RenderedText:
        if _token is not RenderedText._token:
            raise TypeError("RenderedText can only be produced by templates.render()")
        return super().__new__(cls, value)


def validate_slots(template_id: str, slots: dict[str, Any], roster: set[str] | frozenset[str]) -> BaseModel:
    """Validate raw slots for a template against the roster. Raises ``SlotError``."""
    try:
        tid = TemplateId(template_id)
    except ValueError as e:
        raise SlotError(f"unknown template {template_id!r}") from e
    tpl = TEMPLATES[tid]
    try:
        model = tpl.slots_model.model_validate(slots)
    except ValidationError as e:
        raise SlotError(str(e)) from e
    reg = getattr(model, "reg", None)
    if reg is not None and reg not in roster:
        raise SlotError(f"callsign {reg} is not on the desk roster")
    if tpl.needs_reg and reg is None:
        raise SlotError(f"{tid} requires a callsign")
    return model


def _prefix(reg: str | None) -> str:
    return f"MEDEVAC {spoken_reg(reg)}" if reg else "Aircraft calling Landed desk"


def render(template_id: str, slots: dict[str, Any], roster: set[str] | frozenset[str]) -> RenderedText:
    """The only way to produce spoken text. Validates slots (raises ``SlotError``) then fills the template."""
    m = validate_slots(template_id, slots, roster)
    tid = TemplateId(template_id)
    reg = getattr(m, "reg", None)
    p = _prefix(reg)
    match tid:
        case TemplateId.ACK_CHECKIN:
            assert isinstance(m, AckCheckinSlots)
            alt = _digits_words(f"{m.altimeter_inhg:.2f}".replace(".", "")[:4])
            text = f"{p}, Landed advisory, radar contact {POSITIONS[m.position][0]}, altimeter {alt}"
            if m.report_point:
                text += f", report {POSITIONS[m.report_point][0]}"
        case TemplateId.TRAFFIC:
            assert isinstance(m, TrafficSlots)
            dist = _digits_words(f"{m.distance_nm:.1f}".removesuffix(".0"))
            miles = "mile" if m.distance_nm == 1 else "miles"
            text = (
                f"{p}, traffic {_CLOCK[m.clock]} o'clock {dist} {miles} {m.traffic_type} "
                f"{spoken_altitude(m.altitude_ft)}"
            )
        case TemplateId.CORRIDOR_ENTRY:
            assert isinstance(m, CorridorEntrySlots)
            text = f"{p}, enter {m.corridor} {m.direction}bound, report {POSITIONS[m.reporting_point][0]}"
        case TemplateId.REPORT_ACK:
            text = f"{p}, roger"
        case TemplateId.SAY_AGAIN:
            assert isinstance(m, SayAgainSlots)
            text = f"{p}, say again {m.what}"
        case TemplateId.STANDBY_HANDOFF:
            text = f"{p}, standby, controller will be with you"
        case TemplateId.CONTROLLER_TAKING_OVER:
            text = f"{p}, controller taking over"
    return RenderedText(text, _token=RenderedText._token)
