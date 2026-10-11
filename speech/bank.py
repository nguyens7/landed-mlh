"""Load the ground-truth utterance bank and compare parses against it."""

from __future__ import annotations

from pathlib import Path

import yaml

from models import ParsedTransmission
from snap import core

BANK_PATH = Path(__file__).parent / "scripts" / "utterances.yaml"
SLOT_NAMES = ["position", "altitude_ft", "direction", "corridor", "origin", "destination",
              "weather_phrase", "squawk"]


def load_bank(path: Path = BANK_PATH) -> list[dict]:
    items = yaml.safe_load(path.read_text())
    for it in items:
        it.setdefault("slots", {})
        it.setdefault("emergency", False)
        it.setdefault("callsign", {})
        it.setdefault("style", "urgent" if it["emergency"] else "normal")
    return items


def truth_slots(item: dict) -> dict:
    return {k: item["slots"].get(k) for k in SLOT_NAMES}


def pred_slots(pt: ParsedTransmission) -> dict:
    d = pt.slots.model_dump()
    return {k: d.get(k) for k in SLOT_NAMES}


def callsign_exact(item: dict, pt: ParsedTransmission) -> bool:
    t = item["callsign"].get("normalized")
    p = pt.callsign.normalized
    if t is None or p is None:
        return t is None and p is None
    return core(t) == core(p)


def callsign_snapped(item: dict, pt: ParsedTransmission) -> bool:
    """Strict: snapped_to equals the true registration (None == None)."""
    return (item["callsign"].get("snapped_to") or None) == pt.callsign.snapped_to


def callsign_safe(item: dict, pt: ParsedTransmission) -> bool:
    """Correct snap, OR an ambiguity flag whose candidate set contains the true registration."""
    truth = item["callsign"].get("snapped_to")
    if truth is None:
        return pt.callsign.snapped_to is None
    cands = ([pt.callsign.snapped_to] if pt.callsign.snapped_to else []) + pt.callsign.ambiguous_with
    if pt.callsign.ambiguous_with:
        return truth in cands
    return pt.callsign.snapped_to == truth


def slot_diffs(item: dict, pt: ParsedTransmission) -> dict[str, tuple]:
    t, p = truth_slots(item), pred_slots(pt)
    return {k: (t[k], p[k]) for k in SLOT_NAMES if t[k] != p[k]}


def critical_error(item: dict, pt: ParsedTransmission) -> bool:
    """Error that would matter downstream: wrong callsign, intent, emergency flag or any slot."""
    return (not callsign_safe(item, pt)) or pt.intent != item["intent"] or pt.emergency != item["emergency"] \
        or bool(slot_diffs(item, pt))
