"""Canonical agent position IDs for gazetteer place names.

Keys are the canonical names from ``parse.PLACES``. Values are the position IDs the voice agent
uses (``POSITIONS`` in ``agent/landed_agent/templates.py``). Places with no agent position map to
nothing and carry no ``position_id``.
"""

from __future__ import annotations

PLACE_POSITION_IDS: dict[str, str] = {
    "East 34th": "6N5",
    "Downtown Skyport": "JRB",
    "Brooklyn Bridge": "brooklyn_bridge",
    "Williamsburg Bridge": "williamsburg_bridge",
    "Roosevelt Island": "roosevelt_island_north",  # closest agent point; the only Roosevelt Island position defined
    "Intrepid": "intrepid",
    "Statue of Liberty": "statue_of_liberty",
    "George Washington Bridge": "gwb",
    "Governors Island": "governors_island",
}


def position_id_for(place: str | None) -> str | None:
    """Return the agent position ID for a canonical place name, or None if the agent has none."""
    return PLACE_POSITION_IDS.get(place) if place else None
