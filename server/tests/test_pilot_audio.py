from __future__ import annotations

import wave

from landed_server import scenarios_api


def _write_wav(path, seconds: float = 0.5, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


def _build(tmp_path, monkeypatch, seconds: float = 0.5):
    audio = tmp_path / "audio"
    monkeypatch.setattr(scenarios_api, "AUDIO_DIR", audio)
    mf = tmp_path / "manifest.json"
    mf.write_text('{"S2/L1": {"audio": "audio/lines/clip.wav"}}')
    monkeypatch.setattr(scenarios_api, "MANIFEST_FILE", mf)
    _write_wav(audio / "lines" / "clip.wav", seconds)
    return audio / "lines" / "clip.wav"


async def test_pilot_audio_404_when_not_built(client):
    assert (await client.get("/scenario/S2/audio/L1")).status_code == 404
    assert (await client.get("/scenario/S9/audio/L1")).status_code == 404
    assert (await client.get("/scenario/S2/audio/NOPE")).status_code == 404


async def test_pilot_audio_served_via_manifest(client, tmp_path, monkeypatch):
    clip = _build(tmp_path, monkeypatch)
    r = await client.get("/scenario/S2/audio/L1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"
    assert abs(scenarios_api.clip_seconds(clip) - 0.5) < 0.01


async def test_play_reports_audio_and_only_filter(client, tmp_path, monkeypatch):
    _build(tmp_path, monkeypatch, seconds=2.0)
    r = await client.post("/scenario/S2/play", json={"only": ["L1"], "reset": False})
    line = r.json()["lines"][0]
    assert line["audio_url"] == "/scenario/S2/audio/L1"
    assert line["audio_s"] == 2.0
    await client.post("/scenario/reset")
