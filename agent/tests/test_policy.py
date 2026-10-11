"""Policy tiers and the eight mandatory handoff triggers (SPEC section 2). One test per trigger."""

from __future__ import annotations

import pytest
from conftest import make_parsed

from landed_agent.models import AdsbPosition, EngineAlert
from landed_agent.policy import PolicyConfig, Trigger, evaluate, tier_for_rendered
from landed_agent.templates import TemplateId


def _alert(reg: str = "N312LM", severity: str = "handoff") -> EngineAlert:
    return EngineAlert.model_validate(
        {
            "id": f"A-{reg}",
            "aircraft": {"hex": "x", "reg": reg},
            "volume_id": "lga_22_final",
            "severity": severity,
            "confidence": 0.88,
            "reason": "Projected path enters LGA Rwy 22 final",
            "time_to_entry_s": 70,
        }
    )


def assert_handoff(d, trigger: Trigger):
    assert d.tier == "handoff"
    assert trigger in d.triggers
    assert d.forced_template == TemplateId.STANDBY_HANDOFF


# ------------------------------------------------------------- tiers


def test_routine_high_confidence_is_auto(desk):
    d = evaluate(make_parsed(), desk)
    assert d.tier == "auto" and d.triggers == []
    assert d.confidence == pytest.approx(0.95 * 0.97 * d.confidence_parts["geometry"], abs=1e-3)
    assert d.confidence >= 0.8


def test_confidence_is_product_not_hardcoded(desk):
    lo = evaluate(make_parsed(asr=0.7, parse=0.9), desk)
    hi = evaluate(make_parsed(asr=0.99, parse=0.99), desk)
    assert lo.confidence < hi.confidence
    assert set(lo.confidence_parts) == {"asr", "parse", "geometry"}


def test_mid_confidence_needs_approval(desk):
    d = evaluate(make_parsed(asr=0.75, parse=0.9), desk)  # 0.675 x geometry ~1
    assert d.tier == "approval"
    assert 0.5 <= d.confidence < 0.8


def test_below_half_hands_off(desk):
    d = evaluate(make_parsed(asr=0.62, parse=0.7), desk)  # ~0.43
    assert_handoff(d, Trigger.LOW_CONFIDENCE)


def test_active_alert_blocks_auto(desk):
    desk.alerts["a"] = _alert("N405LP", "advisory")
    assert evaluate(make_parsed(), desk).tier == "approval"


def test_landing_content_is_approval_tier():
    assert tier_for_rendered("auto", "MEDEVAC Three One Two Lima Mike, cleared to land") == "approval"
    assert tier_for_rendered("auto", "MEDEVAC Two Six Four Six X-Ray, roger") == "auto"
    assert tier_for_rendered("handoff", "go around") == "handoff"


# ------------------------------------------------------------- the eight triggers


def test_trigger_1_path_intersects_protected_volume(desk):
    desk.alerts["A-N312LM"] = _alert("N312LM")
    d = evaluate(make_parsed(reg="N312LM", position="6N5"), desk)
    assert_handoff(d, Trigger.PATH_PROTECTED_VOLUME)
    assert d.confidence == pytest.approx(0.88)


def test_trigger_2_altitude_at_class_b_floor_minus_100(desk):
    assert_handoff(evaluate(make_parsed(altitude_ft=1200), desk), Trigger.ALTITUDE_CLASS_B)
    assert evaluate(make_parsed(altitude_ft=1100), desk).tier == "auto"
    desk.positions["N2646X"] = AdsbPosition(reg="N2646X", lat=40.7013, lon=-74.0085, alt_ft=1250)
    assert_handoff(evaluate(make_parsed(), desk), Trigger.ALTITUDE_CLASS_B)  # ADS-B altitude alone


@pytest.mark.parametrize(
    ("intent", "text"),
    [
        ("request_route", "request direct Flushing Hospital area"),
        ("checkin", "request Class Bravo transit"),
        ("checkin", "request priority over the arrivals"),
        ("position_report", "crossing LaGuardia final"),
        ("unknown", "something unintelligible about a thing"),
    ],
)
def test_trigger_3_out_of_whitelist_request(desk, intent, text):
    assert_handoff(evaluate(make_parsed(text, intent=intent), desk), Trigger.OUT_OF_WHITELIST)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text": "MAYDAY MAYDAY MAYDAY, MEDEVAC Three One Two Lima Mike, engine chip light"},
        {"text": "pan pan pan pan pan"},
        {"text": "engine chip light", "emergency": True},
        {"text": "garbled", "squawk": "7700"},
        {"text": "garbled", "squawk": "7600"},
        {"text": "garbled", "squawk": "7500"},
    ],
)
def test_trigger_4_emergency(desk, kwargs):
    d = evaluate(make_parsed(**kwargs), desk)
    assert d.tier == "emergency" and Trigger.EMERGENCY in d.triggers
    assert d.forced_template == TemplateId.CONTROLLER_TAKING_OVER


def test_trigger_4_adsb_squawk_is_emergency_regardless_of_parse(desk):
    desk.positions["N312LM"] = AdsbPosition(reg="N312LM", lat=40.7, lon=-73.97, alt_ft=500, squawk="7700")
    d = evaluate(make_parsed("Brooklyn Bridge, five hundred", intent="position_report"), desk)
    assert d.tier == "emergency"


def test_trigger_5_asr_below_threshold_twice(desk):
    first = evaluate(make_parsed(asr=0.4), desk)  # first time: ask to say again
    assert first.tier == "auto" and first.forced_template == TemplateId.SAY_AGAIN
    desk.low_asr_streak = 1
    assert_handoff(evaluate(make_parsed(asr=0.4), desk), Trigger.ASR_LOW_TWICE)


def test_trigger_5_threshold_is_configurable(desk):
    cfg = PolicyConfig(asr_threshold=0.9)
    desk.low_asr_streak = 1
    assert_handoff(evaluate(make_parsed(asr=0.85), desk, cfg), Trigger.ASR_LOW_TWICE)
    assert evaluate(make_parsed(asr=0.85), desk, PolicyConfig()).tier != "handoff"
    assert PolicyConfig().asr_threshold == 0.60


def test_trigger_6_callsign_ambiguity(desk):
    amb = make_parsed(ambiguous_with=["N405LP"], snap=0.6)
    first = evaluate(amb, desk)
    assert first.forced_template == TemplateId.SAY_AGAIN and first.say_again_what == "callsign"
    assert first.reg is None  # never guess a callsign aloud
    desk.ambiguity_streak = 1
    assert_handoff(evaluate(amb, desk), Trigger.CALLSIGN_AMBIGUITY)


def test_trigger_6_unresolved_callsign_is_ambiguous(desk):
    desk.ambiguity_streak = 1
    assert_handoff(evaluate(make_parsed(reg=None), desk), Trigger.CALLSIGN_AMBIGUITY)


def test_trigger_6_transposed_digits_need_adsb_crosscheck(desk):
    desk.roster.append("N2464X")
    parsed = make_parsed(position="Brooklyn Bridge", intent="position_report")
    # Inconclusive: N2646X is nowhere near Brooklyn Bridge, N2464X has no position
    d = evaluate(parsed, desk)
    assert d.forced_template == TemplateId.SAY_AGAIN and d.say_again_what == "callsign"
    desk.ambiguity_streak = 1
    assert_handoff(evaluate(parsed, desk), Trigger.CALLSIGN_AMBIGUITY)


def test_transposed_digits_accepted_when_adsb_supports_the_snap(desk):
    desk.roster.append("N2464X")
    desk.positions["N2646X"] = AdsbPosition(reg="N2646X", lat=40.7061, lon=-73.9969, alt_ft=500)
    desk.positions["N2464X"] = AdsbPosition(reg="N2464X", lat=40.9, lon=-73.93, alt_ft=500)
    d = evaluate(make_parsed(position="Brooklyn Bridge", intent="position_report", altitude_ft=500), desk)
    assert d.tier == "auto"
    assert any("cross-check supports" in e for e in d.evidence)


def test_trigger_6_transposed_digits_rejected_when_adsb_says_other_aircraft(desk):
    desk.roster.append("N2464X")
    desk.positions["N2646X"] = AdsbPosition(reg="N2646X", lat=40.9, lon=-73.93, alt_ft=500)
    desk.positions["N2464X"] = AdsbPosition(reg="N2464X", lat=40.7061, lon=-73.9969, alt_ft=500)
    desk.ambiguity_streak = 1
    parsed = make_parsed(position="Brooklyn Bridge", intent="position_report", altitude_ft=500)
    assert_handoff(evaluate(parsed, desk), Trigger.CALLSIGN_AMBIGUITY)


@pytest.mark.parametrize(
    "text",
    [
        "ceilings coming down, request descend to six hundred",
        "inadvertent IMC",
        "losing visual",
        "request special VFR",
    ],
)
def test_trigger_7_weather_phrases(desk, text):
    assert_handoff(evaluate(make_parsed(text, intent="position_report"), desk), Trigger.WEATHER)


def test_trigger_7_weather_slot(desk):
    assert_handoff(evaluate(make_parsed(weather_phrase="ceilings coming down"), desk), Trigger.WEATHER)


def test_trigger_8_more_than_three_helicopters(desk):
    desk.roster.append("N999ZZ")
    fourth = evaluate(make_parsed(reg="N999ZZ", position="JRB"), desk)
    assert_handoff(fourth, Trigger.DESK_OVER_CAPACITY)
    assert (
        Trigger.DESK_OVER_CAPACITY not in evaluate(make_parsed(), desk).triggers
    )  # first three keep service
