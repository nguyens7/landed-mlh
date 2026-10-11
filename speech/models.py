"""Pydantic contract consumed by the voice-agent track.

JSON Schema export: ``uv run python models.py`` writes schema/parsed_transmission.schema.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["checkin", "position_report", "request_route", "request_altitude",
                 "readback", "emergency", "unknown"]


class Callsign(BaseModel):
    spoken: str | None = Field(None, description="Callsign as spoken, e.g. 'Two Six Four Six X-Ray'")
    normalized: str | None = Field(None, description="Alphanumeric form, e.g. '2646X' or 'N312LM'")
    snapped_to: str | None = Field(None, description="Roster registration the callsign snapped to, e.g. 'N2646X'")
    snap_score: float = Field(0.0, ge=0, le=1, description="Phonetic+digit similarity to snapped_to")
    ambiguous_with: list[str] = Field(default_factory=list,
                                      description="Other roster callsigns within the ambiguity margin (S4)")


class Slots(BaseModel):
    position: str | None = Field(None, description="Canonical place name of the reported position / reporting point")
    position_id: str | None = Field(None, description="Canonical agent position ID for the position, e.g. '6N5' or 'JRB'")
    altitude_ft: int | None = None
    direction: str | None = Field(None, description="e.g. 'northbound'")
    corridor: Literal["Hudson", "East River"] | None = None
    origin: str | None = None
    destination: str | None = None
    weather_phrase: str | None = Field(None, description="Canonical weather phrase, e.g. 'ceilings coming down'")
    squawk: str | None = Field(None, description="4-digit transponder code")


class ParsedTransmission(BaseModel):
    raw_text: str
    asr_confidence: float | None = Field(None, ge=0, le=1, description="exp(mean token logprob); None if unavailable")
    callsign: Callsign = Field(default_factory=Callsign)
    intent: Intent = "unknown"
    slots: Slots = Field(default_factory=Slots)
    emergency: bool = False
    parse_confidence: float = Field(0.0, ge=0, le=1)
    parser: Literal["grammar", "llm"] = "grammar"
    reason: str = Field("", description="Human-readable explanation of how this parse was reached and how "
                                        "confident it is, suitable for an approval card")


def export_schema(path: Path | None = None) -> Path:
    path = path or Path(__file__).parent / "schema" / "parsed_transmission.schema.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ParsedTransmission.model_json_schema(), indent=2) + "\n")
    return path


if __name__ == "__main__":
    print(export_schema())
