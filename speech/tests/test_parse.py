import json
from pathlib import Path

import pytest

from bank import callsign_exact, callsign_safe, load_bank, slot_diffs
from models import ParsedTransmission
from parse import parse_transmission

BANK = load_bank()


@pytest.mark.parametrize("item", BANK, ids=[b["id"] for b in BANK])
def test_grammar_matches_ground_truth(item):
    """Deterministic grammar alone must reproduce the ground truth on clean script text."""
    pt = parse_transmission(item["text"], llm=False)
    assert callsign_exact(item, pt), (item["callsign"], pt.callsign)
    assert callsign_safe(item, pt), (item["callsign"], pt.callsign)
    if item["callsign"].get("ambiguous"):
        assert pt.callsign.ambiguous_with
    assert pt.intent == item["intent"]
    assert pt.emergency == item["emergency"]
    assert not slot_diffs(item, pt), slot_diffs(item, pt)
    assert pt.parser == "grammar"
    assert pt.reason.strip()


def test_bank_size_and_coverage():
    assert len(BANK) >= 45
    assert {b["scenario"] for b in BANK} >= {"S1", "S2", "S3", "S4", "S5"}
    assert {b["intent"] for b in BANK} == {"checkin", "position_report", "request_route", "request_altitude",
                                           "readback", "emergency", "unknown"}


def test_asr_variants_digits_instead_of_words():
    pt = parse_transmission("MEDEVAC Four Zero Six Tango Delta, East 34th, lifting, East River northbound, 1500.", llm=False)
    assert pt.slots.altitude_ft == 1500 and pt.callsign.snapped_to == "N406TD"


def test_confidence_is_evidence_based():
    full = parse_transmission("Landed desk, MEDEVAC Two Six Four Six X-Ray, abeam Brooklyn Bridge, five hundred.", llm=False)
    thin = parse_transmission("Six Four X-Ray, Brooklyn Bridge.", llm=False)
    assert full.parse_confidence > 0.7 > thin.parse_confidence


def test_schema_file_matches_model():
    path = Path(__file__).parent.parent / "schema" / "parsed_transmission.schema.json"
    assert json.loads(path.read_text()) == ParsedTransmission.model_json_schema()
    assert "reason" in json.loads(path.read_text())["properties"]


@pytest.mark.parametrize("text,phrase", [
    ("Ceiling's coming down", "ceilings coming down"),
    ("Ceiling’s coming down", "ceilings coming down"),
    ("ceilings coming down", "ceilings coming down"),
    ("ceiling is coming down", "ceilings coming down"),
    ("Inadvertent IMC, request", "inadvertent imc"),
    ("losing visual over the Intrepid", "losing visual"),
    ("special VFR request", "special vfr"),
])
def test_weather_phrase_variants(text, phrase):
    pt = parse_transmission(text, llm=False)
    assert pt.slots.weather_phrase == phrase


@pytest.mark.parametrize("text,altitude", [
    ("approaching East 34th 500", 500),
    ("approaching East 34th, 500", 500),
    ("34th Street 500 lifting", 500),
    ("approaching West 30th 1500", 1500),
    ("approaching East thirty four 800", 800),
    ("MEDEVAC Two Six Four Six X-Ray, approaching 34th Street, one thousand five hundred", 1500),
])
def test_street_number_never_merges_with_altitude(text, altitude):
    pt = parse_transmission(text, llm=False)
    assert pt.slots.altitude_ft == altitude


def test_street_number_does_not_become_altitude_alone():
    pt = parse_transmission("approaching East 34th", llm=False)
    assert pt.slots.altitude_ft is None
    assert pt.slots.position == "East 34th"


@pytest.mark.parametrize("text,position,position_id", [
    ("approaching East 34th 500", "East 34th", "6N5"),
    ("abeam Downtown Skyport, 500", "Downtown Skyport", "JRB"),
    ("abeam Brooklyn Bridge, 500", "Brooklyn Bridge", "brooklyn_bridge"),
    ("abeam Roosevelt Island, 500", "Roosevelt Island", "roosevelt_island_north"),
    ("abeam Intrepid, 1500", "Intrepid", "intrepid"),
    ("abeam Manhattan Bridge, 1500", "Manhattan Bridge", None),
])
def test_position_id_follows_place_name(text, position, position_id):
    pt = parse_transmission(text, llm=False)
    assert pt.slots.position == position
    assert pt.slots.position_id == position_id


def test_position_id_absent_without_position():
    pt = parse_transmission("MEDEVAC Two Six Four Six X-Ray, lifting, 500", llm=False)
    assert pt.slots.position_id is None


def test_position_ids_exist_in_agent_templates():
    """Every mapped ID must be a POSITIONS key in the agent, so the two packages cannot drift."""
    from places import PLACE_POSITION_IDS

    templates = Path(__file__).parents[2] / "agent" / "landed_agent" / "templates.py"
    if not templates.exists():
        pytest.skip("agent package not present in this checkout")
    src = templates.read_text()
    for pid in set(PLACE_POSITION_IDS.values()):
        assert f'"{pid}":' in src, pid


def test_schema_exposes_position_id():
    path = Path(__file__).parent.parent / "schema" / "parsed_transmission.schema.json"
    assert "position_id" in json.loads(path.read_text())["$defs"]["Slots"]["properties"]
