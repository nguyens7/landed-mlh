"""End-to-end agent flows with a fake model (no network): S1, S2, S5 and the safety fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROSTER, make_parsed

from landed_agent.agent import VoiceAgent
from landed_agent.audit import AuditLog
from landed_agent.desk import DeskState
from landed_agent.gemini_agent import choose
from landed_agent.models import AdsbPosition, EngineAlert, ParsedTransmission
from landed_agent.policy import evaluate
from landed_agent.templates import RenderedText, render
from landed_agent.tts import TTSEngine


def fake_call(name: str, **args):
    return lambda prompt: {"name": name, "args": args}


ACK = {
    "template_id": "ACK_CHECKIN",
    "slots": {"reg": "N2646X", "position": "JRB", "altimeter_inhg": 29.92, "report_point": "brooklyn_bridge"},
    "reason": "routine check-in",
}


def test_s1_routine_checkin_auto_speaks(desk):
    agent = VoiceAgent(fake_call("choose_template", **ACK))
    [p] = agent.handle_transmission(make_parsed(altitude_ft=500), desk, 1000)
    assert p.tier == "auto" and p.status == "auto_spoken" and p.expires_at_ms is None
    assert p.spoken_text_preview.startswith(
        "MEDEVAC Two Six Four Six X-Ray, Landed advisory, radar contact Downtown Skyport"
    )
    assert p.confidence >= 0.8


def test_mid_confidence_becomes_pending_with_10s_expiry(desk):
    agent = VoiceAgent(fake_call("choose_template", **ACK))
    [p] = agent.handle_transmission(make_parsed(asr=0.75, parse=0.9, altitude_ft=500), desk, 5000)
    assert p.tier == "approval" and p.status == "pending"
    assert p.expires_at_ms == 15_000


def test_s2_conflict_alert_produces_standby_handoff_and_card(desk):
    alert = EngineAlert.model_validate(
        {"id": "SIM-1", "aircraft": {"hex": "SIM312LM", "reg": "N312LM"}, "volume_id": "lga22", "severity": "handoff",
         "confidence": 0.88, "reason": "Projected path enters LGA Rwy 22 final", "time_to_entry_s": 70}
    )  # fmt: skip
    agent = VoiceAgent(fake_call("handoff", reason="x"))
    [p] = agent.handle_alerts([alert], desk, 0)
    assert p.template_id == "STANDBY_HANDOFF" and p.status == "handoff_spoken" and p.tier == "handoff"
    assert p.spoken_text_preview == "MEDEVAC Three One Two Lima Mike, standby, controller will be with you"
    assert p.confidence == 0.88 and "path_protected_volume" in p.triggers
    assert agent.handle_alerts([alert], desk, 1000) == []  # answered once per alert id


def test_s2_transmission_with_alert_hands_off_without_calling_model(desk):
    desk.alerts["SIM-1"] = EngineAlert.model_validate(
        {"id": "SIM-1", "aircraft": {"hex": "h", "reg": "N312LM"}, "volume_id": "v", "severity": "handoff",
         "confidence": 0.88, "reason": "r", "time_to_entry_s": 70}
    )  # fmt: skip

    def boom(prompt):
        raise AssertionError("model must not be consulted for a mandatory handoff")

    [p] = VoiceAgent(boom).handle_transmission(
        make_parsed("request direct Flushing Hospital area, one thousand five hundred", reg="N312LM",
                    intent="request_route", altitude_ft=1500), desk, 0)  # fmt: skip
    assert p.tier == "handoff" and p.template_id == "STANDBY_HANDOFF"
    assert {"path_protected_volume", "altitude_class_b", "out_of_whitelist"} <= set(p.triggers)


def test_s5_mayday_one_transmission_then_locked_silent(desk):
    agent = VoiceAgent(fake_call("handoff", reason="x"))
    mayday = make_parsed(
        "MAYDAY MAYDAY MAYDAY, MEDEVAC Three One Two Lima Mike, engine chip light, landing East 34th immediately",
        reg="N312LM", intent="emergency", emergency=True,
    )  # fmt: skip
    props = agent.handle_transmission(mayday, desk, 0)
    spoken = [p for p in props if p.kind == "speak"]
    assert (
        len(spoken) == 1
        and spoken[0].spoken_text_preview == "MEDEVAC Three One Two Lima Mike, controller taking over"
    )
    assert desk.locked
    ops = [p for p in props if p.kind == "notify_ops"]
    assert ops and ops[0].status == "pending" and "TEST number" in ops[0].spoken_text_preview
    again = agent.handle_transmission(make_parsed(), desk, 100)
    assert [p.status for p in again] == ["suppressed"] and again[0].spoken_text_preview == ""
    assert agent.handle_alerts([], desk, 200) == []


def test_adsb_squawk_locks_the_agent(desk):
    agent = VoiceAgent(fake_call("handoff", reason="x"))
    props = agent.handle_adsb(
        AdsbPosition(reg="N312LM", lat=40.7, lon=-73.97, alt_ft=500, squawk="7700"), desk, 0
    )
    assert desk.locked and props[0].spoken_text_preview.endswith("controller taking over")


def test_model_handoff_becomes_standby(desk):
    [p] = VoiceAgent(fake_call("handoff", reason="not routine")).handle_transmission(
        make_parsed(altitude_ft=500), desk, 0
    )
    assert p.tier == "handoff" and p.template_id == "STANDBY_HANDOFF"


def test_s4_garbled_callsign_asks_say_again_then_hands_off(desk):
    agent = VoiceAgent(fake_call("handoff", reason="x"))
    garbled = make_parsed("six four X-ray Brooklyn Bridge", ambiguous_with=["N405LP"], snap=0.6, asr=0.55,
                          position="Brooklyn Bridge")  # fmt: skip
    [first] = agent.handle_transmission(garbled, desk, 0)
    assert first.spoken_text_preview == "Aircraft calling Landed desk, say again callsign"
    [second] = agent.handle_transmission(garbled, desk, 1)
    assert second.tier == "handoff" and "callsign_ambiguity" in second.triggers


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"name": "speak", "args": {"text": "cleared to land runway 22"}},
        {
            "name": "choose_template",
            "args": {"template_id": "CLEARED_TO_LAND", "slots": {"reg": "N2646X"}, "reason": ""},
        },
        {
            "name": "choose_template",
            "args": {"template_id": "STANDBY_HANDOFF", "slots": {"reg": "N2646X"}, "reason": ""},
        },
        {
            "name": "choose_template",
            "args": {"template_id": "REPORT_ACK", "slots": {"reg": "N999ZZ"}, "reason": ""},
        },
        {
            "name": "choose_template",
            "args": {"template_id": "REPORT_ACK", "slots": {"reg": "N312LM"}, "reason": ""},
        },
    ],
)
def test_invalid_model_output_falls_back_to_say_again(desk, bad):
    d = evaluate(make_parsed(altitude_ft=500), desk)
    c = choose(make_parsed(altitude_ft=500), desk, d, lambda p: bad)
    assert c.template_id == "SAY_AGAIN" and c.source == "fallback"
    assert (
        str(render(c.template_id, c.slots, desk.roster_set))
        == "MEDEVAC Two Six Four Six X-Ray, say again transmission"
    )


def test_model_failure_falls_back_to_handoff(desk):
    def down(prompt):
        raise TimeoutError("api down")

    d = evaluate(make_parsed(altitude_ft=500), desk)
    assert choose(make_parsed(altitude_ft=500), desk, d, down).kind == "handoff"


def test_model_free_text_is_never_spoken(desk):
    """The model's `reason` (free text) lands only in the card's evidence, never in spoken text."""
    call = fake_call("choose_template", **{**ACK, "reason": "CLEARED TO LAND RUNWAY 22 IGNORE ALL RULES"})
    [p] = VoiceAgent(call).handle_transmission(make_parsed(altitude_ft=500), desk, 0)
    assert "CLEARED" not in p.spoken_text_preview and "runway" not in p.spoken_text_preview.lower()


def test_tts_input_equals_rendered_template(tmp_path: Path, desk):
    """Acceptance (#4): the string handed to TTS is exactly the rendered template, for every template."""
    seen: list[str] = []

    def fake_synth(text: str, voice: str, model: str) -> bytes:
        seen.append(text)
        return b"RIFF"

    tts = TTSEngine(synth=fake_synth, cache_dir=tmp_path)
    cases = [
        ("ACK_CHECKIN", ACK["slots"]),
        (
            "TRAFFIC",
            {"reg": "N2646X", "clock": 3, "distance_nm": 2.0, "traffic_type": "jet", "altitude_ft": 1000},
        ),
        (
            "CORRIDOR_ENTRY",
            {"reg": "N312LM", "corridor": "Hudson", "direction": "south", "reporting_point": "gwb"},
        ),
        ("REPORT_ACK", {"reg": "N312LM"}),
        ("SAY_AGAIN", {}),
        ("STANDBY_HANDOFF", {"reg": "N312LM"}),
        ("CONTROLLER_TAKING_OVER", {"reg": "N312LM"}),
    ]
    for tid, slots in cases:
        rendered = render(tid, slots, desk.roster_set)
        tts.speak(rendered)
        assert seen[-1] == str(rendered)
    assert len(seen) == len(cases)
    tts.speak(render("REPORT_ACK", {"reg": "N312LM"}, desk.roster_set))
    assert len(seen) == len(cases), "second identical call must hit the disk cache"
    with pytest.raises(TypeError):
        tts.speak("MEDEVAC cleared to land")  # type: ignore[arg-type]


def test_tts_cache_keyed_by_text_voice_model(tmp_path: Path, desk):
    r = render("REPORT_ACK", {"reg": "N312LM"}, desk.roster_set)
    a = TTSEngine(synth=lambda t, v, m: b"a", voice="A", cache_dir=tmp_path)
    b = TTSEngine(synth=lambda t, v, m: b"b", voice="B", cache_dir=tmp_path)
    assert a.speak(r) == b"a" and b.speak(r) == b"b"


def test_audit_log_is_append_only(tmp_path: Path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.append({"id": "1"}, "approve", "sean", 120)
    first = (tmp_path / "a.jsonl").read_bytes()
    log.append({"id": "2"}, "expire", "system", None)
    data = (tmp_path / "a.jsonl").read_bytes()
    assert data.startswith(first), "earlier lines are never rewritten"
    rows = log.read()
    assert [r["decision"] for r in rows] == ["approve", "expire"]
    assert set(rows[0]) == {"ts", "proposal", "decision", "who", "latency_ms"}
    assert not any(hasattr(log, n) for n in ("write", "rewrite", "delete", "truncate", "clear"))


def test_parsed_transmission_matches_track_c_schema():
    """Our local mirror must equal speech/schema/parsed_transmission.schema.json (TODO: import theirs)."""
    path = Path(__file__).resolve().parents[2] / "speech/schema/parsed_transmission.schema.json"
    if not path.exists():
        pytest.skip("speech schema not present")
    assert json.loads(path.read_text()) == ParsedTransmission.model_json_schema()


def test_default_desk_state_is_empty():
    assert DeskState().roster == [] and ROSTER
    assert isinstance(render("REPORT_ACK", {"reg": "N312LM"}, frozenset({"N312LM"})), RenderedText)
