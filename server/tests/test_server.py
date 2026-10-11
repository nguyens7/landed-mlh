from __future__ import annotations

from conftest import parsed
from starlette.testclient import TestClient

from landed_server.app import create_app


async def test_auto_tier_speaks_exact_template_and_logs(client, spoken):
    r = await client.post("/transmission", json=parsed(altitude_ft=500))
    [p] = r.json()["proposals"]
    assert p["status"] == "auto_spoken" and p["audio_ready"]
    audio = await client.get(f"/tts/{p['id']}")
    assert audio.status_code == 200 and audio.content == b"RIFFfake"
    assert p["spoken_text_preview"] in spoken  # TTS got exactly the rendered text
    log = (await client.get("/state")).json()["audit"]
    assert (
        log[-1]["decision"] == "auto_speak"
        and log[-1]["who"] == "agent"
        and log[-1]["latency_ms"] is not None
    )


async def test_pending_audio_is_withheld_until_approved(client, clock):
    r = await client.post("/transmission", json=parsed(asr=0.75, parse=0.9, altitude_ft=500))
    [p] = r.json()["proposals"]
    assert p["status"] == "pending" and p["expires_at_ms"] - p["created_at_ms"] == 10_000
    assert (await client.get(f"/tts/{p['id']}")).status_code == 409
    early = await client.post(
        "/decision", json={"proposal_id": p["id"], "decision": "approve", "who": "sean"}
    )
    assert early.status_code == 425  # 1 s arm delay
    clock.advance(1.2)
    ok = await client.post("/decision", json={"proposal_id": p["id"], "decision": "approve", "who": "sean"})
    assert ok.json()["status"] == "approved"
    assert (await client.get(f"/tts/{p['id']}")).status_code == 200
    last = (await client.get("/state")).json()["audit"][-1]
    assert last["decision"] == "approve" and last["who"] == "sean"


async def test_expired_proposal_is_dropped_never_sent(client, clock, spoken):
    r = await client.post("/transmission", json=parsed(asr=0.75, parse=0.9, altitude_ft=500))
    [p] = r.json()["proposals"]
    clock.advance(10.5)
    late = await client.post("/decision", json={"proposal_id": p["id"], "decision": "approve"})
    assert late.status_code == 410
    assert (await client.get(f"/tts/{p['id']}")).status_code == 410
    prop = next(x for x in (await client.get("/state")).json()["proposals"] if x["id"] == p["id"])
    assert prop["status"] == "expired"
    assert any(a["decision"] == "expire" for a in (await client.get("/state")).json()["audit"])


async def test_expiry_timer_drops_without_any_click(client, clock):
    r = await client.post("/transmission", json=parsed(asr=0.75, parse=0.9, altitude_ft=500))
    [p] = r.json()["proposals"]
    clock.advance(11)
    client.app.state.hub.expire_if_due(p["id"])
    assert client.app.state.hub.proposals[p["id"]].status == "expired"


async def test_reject_takes_over(client, clock):
    [p] = (await client.post("/transmission", json=parsed(asr=0.75, parse=0.9, altitude_ft=500))).json()[
        "proposals"
    ]
    r = await client.post("/decision", json={"proposal_id": p["id"], "decision": "reject"})
    assert r.json()["status"] == "rejected"
    assert (await client.get(f"/tts/{p['id']}")).status_code == 409


async def test_edit_revalidates_and_rearms(client, clock):
    [p] = (await client.post("/transmission", json=parsed(asr=0.75, parse=0.9, altitude_ft=500))).json()[
        "proposals"
    ]
    bad = await client.post(
        "/decision",
        json={"proposal_id": p["id"], "decision": "edit", "slots": {"reg": "N2646X", "position": "LGA"}},
    )
    assert bad.status_code == 422
    clock.advance(5)
    good_slots = {"reg": "N2646X", "position": "6N5", "altimeter_inhg": 30.01}
    ok = await client.post(
        "/decision", json={"proposal_id": p["id"], "decision": "edit", "slots": good_slots}
    )
    body = ok.json()
    assert body["status"] == "pending" and "East 34th Street" in body["spoken_text_preview"]
    assert body["expires_at_ms"] - body["created_at_ms"] == 10_000  # fresh 10 s


async def test_s2_alert_gives_standby_and_human_card(client):
    alert = {"id": "SIM-1", "aircraft": {"hex": "SIM312LM", "reg": "N312LM"}, "volume_id": "lga22", "severity": "handoff",
             "confidence": 0.88, "reason": "Projected path enters LGA Rwy 22 final", "time_to_entry_s": 70,
             "first_seen_t": 1, "last_seen_t": 2, "entry_point": {"lat": 1, "lon": 2}, "entry_alt_ft": 600}  # fmt: skip
    r = await client.post("/alerts", json=[alert])
    [p] = r.json()["proposals"]
    assert p["tier"] == "handoff" and p["spoken_text_preview"].endswith(
        "standby, controller will be with you"
    )
    assert (await client.get(f"/tts/{p['id']}")).status_code == 200
    assert (await client.post("/alerts", json=[alert])).json()["proposals"] == []


async def test_s5_mayday_one_transmission_then_lock(client, clock):
    [pending] = (
        await client.post("/transmission", json=parsed(asr=0.75, parse=0.9, altitude_ft=500))
    ).json()["proposals"]
    mayday = parsed(
        "MAYDAY MAYDAY MAYDAY engine chip light", reg="N312LM", intent="emergency", emergency=True
    )
    props = (await client.post("/transmission", json=mayday)).json()["proposals"]
    assert props[0]["spoken_text_preview"] == "MEDEVAC Three One Two Lima Mike, controller taking over"
    assert props[1]["kind"] == "notify_ops" and "TEST number" in props[1]["spoken_text_preview"]
    assert (await client.get("/health")).json()["locked"]
    # the pending card was dropped by the lock, and further calls are silent
    st = (await client.get("/state")).json()
    assert next(x for x in st["proposals"] if x["id"] == pending["id"])["status"] == "expired"
    after = (await client.post("/transmission", json=parsed(altitude_ft=500))).json()["proposals"]
    assert after[0]["status"] == "suppressed" and after[0]["spoken_text_preview"] == ""
    assert (await client.get(f"/tts/{after[0]['id']}")).status_code == 409
    clock.advance(2)
    ops = await client.post("/decision", json={"proposal_id": props[1]["id"], "decision": "approve"})
    assert ops.json()["status"] == "done"  # notify-ops stub still needs (and gets) a human approval
    await client.post("/unlock", json={"who": "sean"})
    assert not (await client.get("/health")).json()["locked"]


async def test_adsb_squawk_alone_triggers_emergency(client):
    r = await client.post(
        "/adsb", json={"reg": "N312LM", "lat": 40.7, "lon": -73.97, "alt_ft": 500, "squawk": "7700"}
    )
    assert r.json()["proposals"][0]["spoken_text_preview"].endswith("controller taking over")


async def test_caution_alert_gets_traffic_not_handoff(client):
    traffic = [{"clock": 12, "distance_nm": 2.0, "traffic_type": "helicopter", "altitude_ft": 900}]
    await client.post("/desk", json={"roster": ["N2646X"], "traffic": traffic, "merge": True})
    alert = {"id": "C-1", "aircraft": {"hex": "SIM2646X", "reg": "N2646X"}, "volume_id": "sfra_hudson",
             "severity": "caution", "confidence": 0.82, "reason": "Southbound aircraft on the east shoreline",
             "time_to_entry_s": 0}  # fmt: skip
    [p] = (await client.post("/alerts", json=[alert])).json()["proposals"]
    assert p["template_id"] == "TRAFFIC" and p["status"] == "auto_spoken" and p["triggers"] == []
    assert (await client.get(f"/tts/{p['id']}")).status_code == 200


async def test_garbled_mayday_without_callsign_locks(client):
    garbled = parsed("Maday maday, lost tail rotor", reg=None, asr=0.29, parse=0.0, intent="unknown")
    props = (await client.post("/transmission", json=garbled)).json()["proposals"]
    assert props[0]["tier"] == "emergency" and (await client.get("/health")).json()["locked"]


async def test_audit_log_only_grows(client, tmp_path):
    path = tmp_path / "audit.jsonl"
    await client.post("/transmission", json=parsed(altitude_ft=500))
    before = path.read_bytes()
    await client.post("/transmission", json=parsed("x", asr=0.75, parse=0.9, altitude_ft=500))
    await client.post("/reset")
    assert path.read_bytes().startswith(before) and len(path.read_bytes()) > len(before)


def test_websocket_pushes_snapshot_and_proposals(tmp_path):
    from landed_agent.audit import AuditLog
    from landed_agent.tts import TTSEngine

    app = create_app(
        model_call=lambda p: {"name": "handoff", "args": {"reason": "x"}},
        tts=TTSEngine(synth=lambda t, v, m: b"RIFF", cache_dir=tmp_path / "t"),
        audit=AuditLog(tmp_path / "a.jsonl"),
        arm_delay_s=0,
    )
    with TestClient(app) as c:
        c.post("/desk", json={"roster": ["N312LM"]})
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "snapshot"
            c.post("/transmission", json=parsed("MAYDAY", reg="N312LM", intent="emergency", emergency=True))
            seen = {ws.receive_json()["type"] for _ in range(6)}
            assert {"lock", "proposal"} <= seen
