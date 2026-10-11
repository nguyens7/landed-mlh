from __future__ import annotations

from conftest import make_parsed

from landed_agent.gemini_agent import choose
from landed_agent.policy import evaluate
from landed_agent.templates import render


def test_omitted_traffic_slots_are_filled_from_desk_traffic(desk):
    desk.traffic = [{"clock": 3, "distance_nm": 2.0, "traffic_type": "helicopter", "altitude_ft": 700}]
    args = {"template_id": "TRAFFIC", "slots": {"reg": "N2646X", "clock": 3, "distance_nm": 2}, "reason": ""}
    d = evaluate(make_parsed(altitude_ft=500), desk)
    c = choose(make_parsed(altitude_ft=500), desk, d, lambda p: {"name": "choose_template", "args": args})
    assert c.source == "gemini"
    text = str(render(c.template_id, c.slots, desk.roster_set))
    assert text == "MEDEVAC Two Six Four Six X-Ray, traffic three o'clock two miles helicopter seven hundred"


def test_unknown_slot_keys_are_dropped_not_spoken(desk):
    args = {"template_id": "REPORT_ACK", "slots": {"reg": "N2646X", "text": "cleared to land"}, "reason": ""}
    d = evaluate(make_parsed(altitude_ft=500), desk)
    c = choose(make_parsed(altitude_ft=500), desk, d, lambda p: {"name": "choose_template", "args": args})
    assert c.source == "gemini" and c.slots == {"reg": "N2646X"}
    assert str(render(c.template_id, c.slots, desk.roster_set)) == "MEDEVAC Two Six Four Six X-Ray, roger"


def test_position_id_case_is_normalised(desk):
    args = {"template_id": "ACK_CHECKIN", "slots": {"reg": "N2646X", "position": "jrb", "altimeter_inhg": 29.92}, "reason": ""}
    d = evaluate(make_parsed(altitude_ft=500), desk)
    c = choose(make_parsed(altitude_ft=500), desk, d, lambda p: {"name": "choose_template", "args": args})
    assert c.source == "gemini" and c.slots["position"] == "JRB"
