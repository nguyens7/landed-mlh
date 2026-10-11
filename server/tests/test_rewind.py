from __future__ import annotations

from conftest import parsed

ALERT = {
    "id": "SIM312LM",
    "aircraft": {"hex": "SIM312LM", "reg": "N312LM"},
    "volume_id": "v",
    "severity": "handoff",
    "confidence": 0.9,
    "reason": "r",
    "time_to_entry_s": 60,
    "also_volumes": ["w"],
}


async def test_rewind_drops_pending_and_alert_can_fire_again(client):
    assert len((await client.post("/alerts", json=[ALERT])).json()["proposals"]) == 1
    assert (await client.post("/alerts", json=[ALERT])).json()["proposals"] == []  # one per aircraft
    [p] = (await client.post("/transmission", json=parsed(asr=0.75, parse=0.9, altitude_ft=500))).json()[
        "proposals"
    ]
    assert (await client.post("/rewind")).json()["dropped"] == 1
    assert client.app.state.hub.proposals[p["id"]].status == "expired"
    assert (
        len((await client.post("/alerts", json=[ALERT])).json()["proposals"]) == 1
    )  # fires again after rewind
    await client.post("/alerts", json=[])  # alert cleared
    assert len((await client.post("/alerts", json=[ALERT])).json()["proposals"]) == 1
