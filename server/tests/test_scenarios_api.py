from __future__ import annotations

import asyncio

from test_rewind import ALERT

from landed_server import scenarios_api


async def test_play_unknown_scenario_is_404(client):
    r = await client.post("/scenario/S9/play")
    assert r.status_code == 404


async def test_play_returns_timed_lines_and_posts_them(client, spoken):
    r = await client.post("/scenario/S1/play", json={"speed": 32})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "S1"
    assert [ln["id"] for ln in body["lines"]] == ["L1", "L2", "L3", "L4"]
    assert abs(body["lines"][0]["in_s"] - 10 / 32) < 0.01
    hub = client.app.state.hub
    for _ in range(100):
        if len(hub.proposals) >= 4:
            break
        await asyncio.sleep(0.1)
    assert len(hub.proposals) >= 4
    assert (await client.get("/scenario/status")).json()["id"] == "S1"


async def test_reset_clears_desk_proposals_and_lock(client):
    hub = client.app.state.hub
    await client.post("/alerts", json=[ALERT])
    hub.desk.locked = True
    assert hub.proposals and hub.desk.roster
    r = await client.post("/scenario/reset")
    assert r.json() == {"ok": True, "locked": False}
    assert not hub.proposals and not hub.order
    assert hub.desk.roster == [] and hub.desk.locked is False


async def test_reset_stops_playback(client):
    await client.post("/scenario/S2/play", json={"speed": 1})  # first line is ~200 s away
    assert (await client.get("/scenario/status")).json()["playing"] is True
    await client.post("/scenario/reset")
    assert (await client.get("/scenario/status")).json() == {"playing": False, "id": None}


def test_all_scenarios_have_pins():
    for sid in scenarios_api.SCENARIO_IDS:
        _, lines = scenarios_api.load_scenario(sid)
        assert lines and all(ln["parsed"]["callsign"] for ln in lines)
