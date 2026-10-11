"""Shared data contracts for the voice agent.

``ParsedTransmission`` mirrors ``speech/models.py`` (Track C). TODO: import theirs once ``speech`` is a
installable package; until then ``tests/test_contract.py`` asserts the two JSON schemas are identical.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- Track C contract (mirror)

Intent = Literal[
    "checkin", "position_report", "request_route", "request_altitude", "readback", "emergency", "unknown"
]


class Callsign(BaseModel):
    spoken: str | None = Field(None, description="Callsign as spoken, e.g. 'Two Six Four Six X-Ray'")
    normalized: str | None = Field(None, description="Alphanumeric form, e.g. '2646X' or 'N312LM'")
    snapped_to: str | None = Field(
        None, description="Roster registration the callsign snapped to, e.g. 'N2646X'"
    )
    snap_score: float = Field(0.0, ge=0, le=1, description="Phonetic+digit similarity to snapped_to")
    ambiguous_with: list[str] = Field(
        default_factory=list, description="Other roster callsigns within the ambiguity margin (S4)"
    )


class Slots(BaseModel):
    position: str | None = Field(
        None, description="Canonical place name of the reported position / reporting point"
    )
    position_id: str | None = Field(
        None, description="Canonical agent position ID for the position, e.g. '6N5' or 'JRB'"
    )
    altitude_ft: int | None = None
    direction: str | None = Field(None, description="e.g. 'northbound'")
    corridor: Literal["Hudson", "East River"] | None = None
    origin: str | None = None
    destination: str | None = None
    weather_phrase: str | None = Field(
        None, description="Canonical weather phrase, e.g. 'ceilings coming down'"
    )
    squawk: str | None = Field(None, description="4-digit transponder code")


class ParsedTransmission(BaseModel):
    raw_text: str
    asr_confidence: float | None = Field(
        None, ge=0, le=1, description="exp(mean token logprob); None if unavailable"
    )
    callsign: Callsign = Field(default_factory=Callsign)
    intent: Intent = "unknown"
    slots: Slots = Field(default_factory=Slots)
    emergency: bool = False
    parse_confidence: float = Field(0.0, ge=0, le=1)
    parser: Literal["grammar", "llm"] = "grammar"
    reason: str = Field(
        "",
        description="Human-readable explanation of how this parse was reached and how "
        "confident it is, suitable for an approval card",
    )


# ---------------------------------------------------------------- engine alert (issue #9)


class AlertAircraft(BaseModel):
    hex: str
    reg: str


class EngineAlert(BaseModel):
    """``Alert`` emitted by ``app/src/engine`` (issue #9). Extra engine fields are ignored."""

    model_config = {"extra": "ignore"}

    id: str
    aircraft: AlertAircraft
    volume_id: str
    severity: Literal["advisory", "caution", "handoff"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    time_to_entry_s: float
    entry_point: dict[str, float] | None = None
    entry_alt_ft: float | None = None
    also_volumes: list[str] = Field(default_factory=list)


class AdsbPosition(BaseModel):
    reg: str
    lat: float
    lon: float
    alt_ft: float | None = None
    squawk: str | None = None


# ---------------------------------------------------------------- proposals

Tier = Literal["auto", "approval", "handoff", "emergency", "suppressed"]
Status = Literal[
    "auto_spoken",  # tier auto: spoken and logged
    "pending",  # waiting for a human click
    "approved",
    "rejected",
    "expired",  # dropped, never sent
    "handoff_spoken",  # STANDBY_HANDOFF / controller-taking-over was spoken; human owns it now
    "suppressed",  # emergency lock active: nothing spoken
    "done",  # non-speech proposal completed (notify-ops stub)
]


class Proposal(BaseModel):
    id: str
    kind: Literal["speak", "notify_ops"] = "speak"
    tier: Tier
    status: Status
    reg: str | None = None
    template_id: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    spoken_text_preview: str = ""
    confidence: float = 0.0
    confidence_parts: dict[str, float | None] = Field(default_factory=dict)
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    heard: str = ""
    created_at_ms: int = 0
    expires_at_ms: int | None = None
    audio_ready: bool = False
    latency_ms: int | None = None
    source: str = "policy"  # "gemini" | "policy" | "fallback"
    router: dict[str, Any] | None = (
        None  # RouterDecision fields (label, probabilities, provider, ...), advisory
    )
