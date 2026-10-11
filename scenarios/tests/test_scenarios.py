"""Scenario-file schema, route-vs-volume validation, engine parity, adapter normalisation and scoring logic."""

from __future__ import annotations

import json

import pytest

import adapter
import paths
import scn_checks
import scn_engine
import scn_geo
import scn_model
import scn_tracks
import scn_validate
import scoring
from scn_model import ParseExpect, ResponseExpect

SCENARIOS = scn_model.load_all()
IDS = list(SCENARIOS)


def test_all_seven_scenarios_present():
    assert IDS == ["S1", "S2", "S3A", "S3B", "S4", "S5", "S6"]


@pytest.mark.parametrize("sid", IDS)
def test_schema_loads_and_lines_reference_aircraft(sid):
    sc = SCENARIOS[sid]
    assert sc.lines and sc.aircraft
    assert all(a.reg.startswith("N") for a in sc.aircraft)  # fictional registrations only


@pytest.mark.parametrize("sid", IDS)
def test_route_vs_volume_and_corridors(sid):
    sc = SCENARIOS[sid]
    assert scn_validate.validate(sc, scn_tracks.build_tracks(sc)) == []


def test_s2_enters_rwy22_final_and_others_do_not():
    for sid, sc in SCENARIOS.items():
        tr = scn_tracks.build_tracks(sc)
        entered = set().union(*(scn_geo.volumes_entered(a["points"]) for a in tr["aircraft"]))
        if sid == "S2":
            assert any(v.startswith("lga22_final_seg") for v in entered)
        else:
            assert not entered, (sid, entered)


def test_s2_track_equals_replay_sim_medevac():
    mine = scn_tracks.build_tracks(SCENARIOS["S2"])["aircraft"][0]
    ref = json.loads((paths.APP_DATA / "replay" / "sim_medevac.json").read_text())["aircraft"][0]
    # Float math differs in the last digits across platforms, so compare numerically, not exactly.
    assert len(mine["points"]) == len(ref["points"])
    for a, b in zip(mine["points"], ref["points"], strict=True):
        assert a.keys() == b.keys()
        assert a == {k: pytest.approx(v, abs=1e-6) if isinstance(v, float) else v for k, v in b.items()}


def test_s2_engine_handoff_lead_about_84s():
    tr = scn_tracks.build_tracks(SCENARIOS["S2"])
    eps = scn_engine.run_engine(tr["aircraft"], 0, 700)
    h = next(e for e in eps if e["severity"] == "handoff" and e["volume_id"].startswith("lga22_final_seg"))
    assert 80 <= h["lead_s_at_first"] <= 90 and h["peak_confidence"] >= 0.8


def test_s3b_shoreline_alert_with_opposing_traffic():
    tr = scn_tracks.build_tracks(SCENARIOS["S3B"])
    hit = scn_checks.shoreline_rule(tr, "N2646X")[0]
    assert hit["direction"] == "southbound" and hit["offset_east_nm"] > scn_checks.LANE_TOLERANCE_NM
    assert 0.5 <= hit["opposing_traffic"]["nm"] <= 3.5
    assert scn_checks.shoreline_rule(scn_tracks.build_tracks(SCENARIOS["S3A"]), "N2646X") == []


def test_s5_squawk_and_s6_desk_count():
    assert (
        scn_checks.squawk_emergency(scn_tracks.build_tracks(SCENARIOS["S5"]), "N312LM")[0]["code"] == "7700"
    )
    assert scn_checks.desk_count(scn_tracks.build_tracks(SCENARIOS["S6"]), 57)["count"] == 4


def test_unknown_trigger_rejected():
    with pytest.raises(ValueError):
        ResponseExpect(triggers=["made_up"])


# ------------------------------------------------------------------ scoring
def parsed(**over):
    base = {
        "callsign": {"snapped_to": "N2646X", "ambiguous_with": []},
        "intent": "position_report",
        "slots": {"altitude_ft": 520, "position": "Brooklyn Bridge"},
        "emergency": False,
    }
    base.update(over)
    return base


def test_altitude_tolerance_plus_minus_50():
    exp = ParseExpect(slots={"altitude_ft": 500})
    assert scoring.score_parse("x", exp, parsed(), 0.9)[0].status == "pass"
    off = parsed(slots={"altitude_ft": 560})
    assert scoring.score_parse("x", exp, off, 0.9)[0].status == "fail"


def test_slot_strings_case_insensitive_and_none_expected():
    exp = ParseExpect(slots={"position": "brooklyn bridge", "weather_phrase": None})
    checks = scoring.score_parse("x", exp, parsed(), 0.9)
    assert len(checks) == 2 and all(c.status == "pass" for c in checks)


def test_trigger_sets_partial_and_fail():
    assert scoring.match_set(["weather"], ["weather"])[0] == "pass"
    assert scoring.match_set(["weather"], ["weather", "out_of_whitelist"])[0] == "partial"
    assert scoring.match_set(["weather", "x"], ["weather"])[0] == "partial"
    assert scoring.match_set(["weather"], ["emergency"])[0] == "fail"


def test_callsign_ambiguity_expectations():
    exp = ParseExpect(callsign={"ambiguous": True, "candidates_include": ["N2646X", "N2464X"]})
    p = parsed(callsign={"snapped_to": "N2464X", "ambiguous_with": ["N2646X"]})
    assert all(c.status == "pass" for c in scoring.score_parse("x", exp, p, 0.5))


def test_response_pending_without_server_and_gap():
    exp = ResponseExpect(mode="speak", template_id="ACK_CHECKIN", tier="auto")
    assert {c.status for c in scoring.score_response("x", exp, None)} == {"pending"}
    gap = ResponseExpect(template_id="TRAFFIC", known_gap="not implemented")
    out = scoring.score_response("x", gap, {"template_id": None})
    assert out[0].status == "gap"
    assert scoring.status_of(out) == "gap"


def test_latency_budget():
    exp = ResponseExpect(mode="speak", tier="auto")
    ok = {"mode": "speak", "tier": "auto"}
    assert scoring.score_response("x", exp, ok, 1200)[-1].status == "pass"
    assert scoring.score_response("x", exp, ok, 3600)[-1].status == "fail"


def test_three_of_three_logic():
    ck = scoring.Check
    good = [ck("a", "f", 1, 1, "pass"), ck("b", "f", 1, None, "pending")]
    bad = [ck("a", "f", 1, 2, "fail"), ck("b", "f", 1, None, "pending")]
    assert scoring.three_of_three([good, good, good])["all_judged_passed_every_run"]
    assert not scoring.three_of_three([good, bad, good])["all_judged_passed_every_run"]


# ------------------------------------------------------------------ adapter
def proposal(**kw):
    p = {
        "id": "abc",
        "kind": "speak",
        "tier": "auto",
        "status": "auto_spoken",
        "template_id": "REPORT_ACK",
        "spoken_text_preview": "MEDEVAC X, roger",
        "reason": "r",
        "evidence": [],
        "triggers": [],
        "source": "gemini",
    }
    p.update(kw)
    return p


def test_normalize_auto_handoff_emergency_locked():
    assert adapter.normalize([proposal()])["mode"] == "speak"
    h = adapter.normalize(
        [
            proposal(
                tier="handoff", status="handoff_spoken", template_id="STANDBY_HANDOFF", triggers=["weather"]
            )
        ]
    )
    assert (h["mode"], h["tier"], h["triggers"]) == ("handoff", "handoff", ["weather"])
    e = adapter.normalize(
        [
            proposal(tier="emergency", status="handoff_spoken", template_id="CONTROLLER_TAKING_OVER"),
            proposal(
                id="n",
                kind="notify_ops",
                tier="approval",
                status="pending",
                template_id=None,
                spoken_text_preview="SIMULATED call to heliport ops",
            ),
        ]
    )
    assert e["tier"] == "handoff" and "heliport ops" in e["card_text"]
    assert adapter.normalize([], locked=True)["mode"] == "locked_silent"
    assert adapter.normalize([proposal(tier="suppressed", status="suppressed")])["mode"] == "locked_silent"
    assert adapter.normalize([proposal(tier="approval", status="pending")])["mode"] == "card"


def test_adapter_against_mock_transport():
    import httpx

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/health":
            return httpx.Response(200, json={"ok": True, "locked": False})
        if req.url.path == "/transmission":
            body = json.loads(req.content)
            assert body["slots"]["position"] == "JRB"  # speech name mapped to the agent's position id
            return httpx.Response(200, json={"proposals": [proposal()], "latency_ms": 5})
        return httpx.Response(404)

    ad = adapter.ServerAdapter("http://x", transport=httpx.MockTransport(handler))
    assert ad.available()
    rep = ad.post_transmission({"raw_text": "t", "slots": {"position": "Downtown Skyport"}})
    assert rep.ok and rep.outcome["template_id"] == "REPORT_ACK" and rep.server_ms == 5
