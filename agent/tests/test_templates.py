from __future__ import annotations

import json
from pathlib import Path

import pytest

from landed_agent.templates import (
    POSITIONS,
    RenderedText,
    SlotError,
    TemplateId,
    render,
    spoken_reg,
    validate_slots,
)

ROSTER = frozenset({"N2646X", "N312LM"})


def test_spoken_reg():
    assert spoken_reg("N2646X") == "Two Six Four Six X-Ray"
    assert spoken_reg("N312LM") == "Three One Two Lima Mike"


def test_all_templates_render():
    cases = {
        "ACK_CHECKIN": {
            "reg": "N2646X",
            "position": "JRB",
            "altimeter_inhg": 29.92,
            "report_point": "brooklyn_bridge",
        },
        "TRAFFIC": {
            "reg": "N2646X",
            "clock": 3,
            "distance_nm": 2.5,
            "traffic_type": "helicopter",
            "altitude_ft": 700,
        },
        "CORRIDOR_ENTRY": {
            "reg": "N2646X",
            "corridor": "East River",
            "direction": "north",
            "reporting_point": "brooklyn_bridge",
        },
        "REPORT_ACK": {"reg": "N2646X"},
        "SAY_AGAIN": {"what": "callsign"},
        "STANDBY_HANDOFF": {"reg": "N312LM"},
        "CONTROLLER_TAKING_OVER": {"reg": "N312LM"},
    }
    assert set(cases) == {t.value for t in TemplateId}
    out = {k: str(render(k, v, ROSTER)) for k, v in cases.items()}
    assert out["ACK_CHECKIN"] == (
        "MEDEVAC Two Six Four Six X-Ray, Landed advisory, radar contact Downtown Skyport, "
        "altimeter two niner niner two, report Brooklyn Bridge"
    )
    assert (
        out["TRAFFIC"]
        == "MEDEVAC Two Six Four Six X-Ray, traffic three o'clock two point five miles helicopter seven hundred"
    )
    assert (
        out["CORRIDOR_ENTRY"]
        == "MEDEVAC Two Six Four Six X-Ray, enter East River northbound, report Brooklyn Bridge"
    )
    assert out["REPORT_ACK"] == "MEDEVAC Two Six Four Six X-Ray, roger"
    assert out["SAY_AGAIN"] == "Aircraft calling Landed desk, say again callsign"
    assert out["STANDBY_HANDOFF"] == "MEDEVAC Three One Two Lima Mike, standby, controller will be with you"
    assert out["CONTROLLER_TAKING_OVER"] == "MEDEVAC Three One Two Lima Mike, controller taking over"


@pytest.mark.parametrize(
    ("template", "slots"),
    [
        ("ACK_CHECKIN", {"reg": "N999ZZ", "position": "JRB", "altimeter_inhg": 29.92}),  # not on roster
        (
            "ACK_CHECKIN",
            {"reg": "N2646X", "position": "LGA runway 22", "altimeter_inhg": 29.92},
        ),  # not in enum
        ("ACK_CHECKIN", {"reg": "N2646X", "position": "JRB", "altimeter_inhg": 99}),  # range
        (
            "TRAFFIC",
            {"reg": "N2646X", "clock": 13, "distance_nm": 2, "traffic_type": "jet", "altitude_ft": 700},
        ),
        (
            "TRAFFIC",
            {"reg": "N2646X", "clock": 3, "distance_nm": 2, "traffic_type": "jet", "altitude_ft": 750},
        ),
        (
            "TRAFFIC",
            {"reg": "N2646X", "clock": 3, "distance_nm": 99, "traffic_type": "jet", "altitude_ft": 700},
        ),
        (
            "CORRIDOR_ENTRY",
            {
                "reg": "N2646X",
                "corridor": "Hudson",
                "direction": "north",
                "reporting_point": "brooklyn_bridge",
            },
        ),
        (
            "CORRIDOR_ENTRY",
            {"reg": "N2646X", "corridor": "Harlem", "direction": "north", "reporting_point": "gwb"},
        ),
        ("REPORT_ACK", {"reg": "N2646X", "extra": "cleared Class Bravo"}),  # no free-form slots
        ("REPORT_ACK", {}),
        ("CLEARED_TO_LAND", {"reg": "N2646X"}),
    ],
)
def test_invalid_slots_rejected(template, slots):
    with pytest.raises(SlotError):
        render(template, slots, ROSTER)


def test_no_template_can_carry_free_text_or_clearance():
    corridor = {"reg": "N312LM", "corridor": "Hudson", "direction": "south", "reporting_point": "gwb"}
    texts = [
        str(render("REPORT_ACK", {"reg": "N312LM"}, ROSTER)),
        str(render("SAY_AGAIN", {}, ROSTER)),
        str(render("STANDBY_HANDOFF", {"reg": "N312LM"}, ROSTER)),
        str(render("CONTROLLER_TAKING_OVER", {"reg": "N312LM"}, ROSTER)),
        str(render("CORRIDOR_ENTRY", corridor, ROSTER)),
    ]
    for text in texts:
        for banned in (
            "cleared",
            "landing",
            " land ",
            "runway",
            "approach",
            "bravo",
            "turn",
            "climb",
            "descend",
            "heading",
        ):
            assert banned not in text.lower()


def test_rendered_text_cannot_be_forged():
    with pytest.raises(TypeError):
        RenderedText("MEDEVAC cleared to land")
    assert isinstance(render("REPORT_ACK", {"reg": "N312LM"}, ROSTER), RenderedText)


def test_validate_returns_typed_model():
    m = validate_slots("REPORT_ACK", {"reg": " n312lm "}, ROSTER)
    assert m.reg == "N312LM"


def test_positions_match_geo_reference_points():
    geo = Path(__file__).resolve().parents[2] / "app/public/data/geo/reference_points.geojson"
    if not geo.exists():
        pytest.skip("geo not present")
    feats = {f["properties"]["id"]: f for f in json.loads(geo.read_text())["features"]}
    assert set(POSITIONS) == set(feats)
    for pid, (_, lon, lat, corridor) in POSITIONS.items():
        assert feats[pid]["geometry"]["coordinates"] == pytest.approx([lon, lat])
        assert feats[pid]["properties"].get("corridor") == corridor
