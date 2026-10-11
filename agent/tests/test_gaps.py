"""Scenario gaps: S3B caution -> TRAFFIC, S4 ADS-B hint, S3A below-transit-min, and the ASR-independent
emergency gate (issue #16, real garbled transcripts from speech/RESULTS.md)."""

from __future__ import annotations

import pytest
from conftest import make_parsed

from landed_agent.agent import VoiceAgent
from landed_agent.models import AdsbPosition, EngineAlert
from landed_agent.policy import Trigger, emergency_gate, evaluate, hudson_transit_min_ft

TRAFFIC = {"clock": 12, "distance_nm": 2.0, "traffic_type": "helicopter", "altitude_ft": 900}


def no_model(prompt):  # a caution / emergency must never reach the model
    raise AssertionError("model called")


def _caution(conf: float, reg: str = "N2646X") -> EngineAlert:
    return EngineAlert.model_validate(
        {"id": f"C-{reg}", "aircraft": {"hex": "x", "reg": reg}, "volume_id": "sfra_hudson", "severity": "caution",
         "confidence": conf, "reason": "Southbound aircraft on the east shoreline", "time_to_entry_s": 0}
    )  # fmt: skip


# ------------------------------------------------------------- S3B


def test_caution_high_confidence_auto_speaks_traffic(desk):
    desk.traffic = [TRAFFIC]
    agent = VoiceAgent(no_model)
    [p] = agent.handle_alerts([_caution(0.82)], desk, 0)
    assert p.template_id == "TRAFFIC" and p.status == "auto_spoken" and p.tier == "auto"
    assert "traffic twelve o'clock" in p.spoken_text_preview and p.triggers == []
    assert agent.handle_alerts([_caution(0.82)], desk, 1000) == []  # once per aircraft


def test_caution_low_confidence_is_an_approval_card(desk):
    desk.traffic = [TRAFFIC]
    [p] = VoiceAgent(no_model).handle_alerts([_caution(0.7)], desk, 0)
    assert p.template_id == "TRAFFIC" and p.status == "pending" and p.tier == "approval"


def test_caution_never_hands_off(desk):
    agent = VoiceAgent(no_model)
    assert agent.handle_alerts([_caution(0.95)], desk, 0) == []  # no traffic to cite: nothing, not a handoff
    desk.traffic = [{"clock": 99}]  # invalid traffic data: still nothing
    assert agent.handle_alerts([_caution(0.95)], desk, 0) == []


def test_caution_suppressed_while_locked(desk):
    desk.traffic = [TRAFFIC]
    desk.locked = True
    assert VoiceAgent(no_model).handle_alerts([_caution(0.9)], desk, 0) == []


# ------------------------------------------------------------- S4


def test_ambiguous_handoff_card_carries_adsb_position_match(desk):
    desk.positions["N2464X"] = AdsbPosition(reg="N2464X", lat=40.80, lon=-73.90, alt_ft=500)
    desk.roster.append("N2464X")
    desk.positions["N2646X"] = AdsbPosition(
        reg="N2646X", lat=40.7061, lon=-73.9969, alt_ft=500
    )  # Brooklyn Bridge
    desk.ambiguity_streak = 1
    p = make_parsed("six four x-ray abeam Brooklyn Bridge", ambiguous_with=["N2464X"], position="Brooklyn Bridge",
                    intent="position_report")  # fmt: skip
    d = evaluate(p, desk)
    assert Trigger.CALLSIGN_AMBIGUITY in d.triggers
    assert any(
        e.startswith("likely N2646X (ADS-B position match") and "unconfirmed by voice" in e
        for e in d.evidence
    )


# ------------------------------------------------------------- S3A


def test_transit_minimum_comes_from_geo_data():
    assert hudson_transit_min_ft() == 1000


def test_hudson_request_below_transit_min_hands_off(desk):
    p = make_parsed(
        "request descend to six hundred", intent="request_altitude", corridor="Hudson", altitude_ft=600
    )
    d = evaluate(p, desk)
    assert d.tier == "handoff" and Trigger.BELOW_TRANSIT_MIN in d.triggers


def test_hudson_check_in_at_transit_min_is_not_below(desk):
    d = evaluate(make_parsed(corridor="Hudson", altitude_ft=1000), desk)
    assert Trigger.BELOW_TRANSIT_MIN not in d.triggers
    d = evaluate(make_parsed(corridor="East River", intent="request_altitude", altitude_ft=600), desk)
    assert Trigger.BELOW_TRANSIT_MIN not in d.triggers


# ------------------------------------------------------------- emergency gate (#16)

# Verbatim low-SNR ASR output from speech/RESULTS.md (s5_05 at -5 dB) plus plausible one-edit garbles.
GARBLED = [
    "Mayday Mayday Mayday. November 724 Bravo Lima. Lost tail rotor. River Northbound, Roosevelt Island for an",
    "Maday maday maday three twelve lima mike",
    "may-day, may-day engine failure",
    "May day May day",
    "Pam pam pam pam, 312 Lima Mike",
    "pan-pan pan-pan",
    "Declaring an emergancy",
]


@pytest.mark.parametrize("text", GARBLED)
def test_gate_fires_on_garbled_text(text):
    assert emergency_gate(text)


@pytest.mark.parametrize("text", GARBLED)
def test_garbled_emergency_locks_even_when_parse_failed(desk, text):
    """No callsign, ASR 0.29, intent unknown, no emergency flag: the gate alone must lock."""
    p = make_parsed(text, reg=None, asr=0.29, parse=0.0, intent="unknown", position=None)
    agent = VoiceAgent(no_model)
    props = agent.handle_transmission(p, desk, 0)
    assert desk.locked and props[0].tier == "emergency" and props[0].status == "handoff_spoken"
    assert any(x.kind == "notify_ops" for x in props)
    after = agent.handle_transmission(make_parsed(altitude_ft=500), desk, 1000)
    assert after[0].status == "suppressed"


@pytest.mark.parametrize(
    "text",
    ["", "Landed desk, MEDEVAC 312 Lima Mike, Downtown Skyport northbound, five hundred", "Monday morning"],
)
def test_gate_does_not_fire_on_routine_text(text):
    assert not emergency_gate(text)
