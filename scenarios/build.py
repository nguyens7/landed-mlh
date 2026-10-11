"""Build step: scenario YAML -> tracks.json, lines.json, index.json, manifest.json (+ optional pilot audio).

    uv run python build.py                  # tracks, lines, manifest (no network)
    uv run python build.py --audio          # also synthesize pilot audio with Gemini TTS + radio filter
    uv run python build.py --audio --ids S1,S4
    uv run python build.py --check          # validate routes against the real geo, write nothing
    uv run python build.py --prewarm        # start the server, play S1-S6 once: caches picker answers + agent TTS audio

Outputs (relative to the repo root):
    app/public/data/scenarios/<id>/tracks.json   replay schema, same as replay/sim_medevac.json
    app/public/data/scenarios/<id>/lines.json    timed pilot lines with audio paths and the expected outcomes
    app/public/data/scenarios/index.json         list of scenarios for a later UI picker
    scenarios/manifest.json                      text hashes so audio can be regenerated (committed)
    scenarios/audio/                             pilot audio (gitignored)
"""

from __future__ import annotations

import argparse
import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import paths
import scn_audio
import scn_model
import scn_tracks
import scn_validate


def lines_json(sc: scn_model.Scenario, tracks: dict) -> dict:
    return {
        "scenario": sc.id,
        "title": sc.title,
        "note": "SIMULATION ONLY. Fictional registrations. Frequency shown as SIM DESK.",
        "lines": [
            {
                "id": ln.id,
                "t": ln.t,
                "aircraft": ln.aircraft,
                "spoken_callsign": sc.aircraft_by_reg(ln.aircraft).spoken,
                "text": ln.text,
                "voice": scn_audio.line_voice(sc, ln),
                "snr": ln.snr,
                "rotor": ln.rotor,
                "style": ln.style,
                "audio": f"audio/{scn_audio.audio_path(sc, ln).name}",
                "hash": scn_audio.text_hash(sc, ln),
                "expect": ln.expect.model_dump(exclude_none=True, exclude_defaults=True),
            }
            for ln in sorted(sc.lines, key=lambda x: x.t)
        ],
        "events": [e.model_dump(exclude_none=True, exclude_defaults=True) for e in sc.events],
    }


def build_one(sc: scn_model.Scenario, make_audio: bool, publish_audio: bool) -> tuple[dict, list[str]]:
    tracks = scn_tracks.build_tracks(sc)
    errors = scn_validate.validate(sc, tracks)
    out = paths.OUT_DIR / sc.id
    out.mkdir(parents=True, exist_ok=True)
    (out / "tracks.json").write_text(json.dumps(tracks))
    (out / "lines.json").write_text(json.dumps(lines_json(sc, tracks), indent=1) + "\n")
    if make_audio:
        with ThreadPoolExecutor(3) as ex:
            list(ex.map(lambda ln: scn_audio.render_line(sc, ln), sc.lines))
    if publish_audio:
        for ln in sc.lines:
            src = scn_audio.audio_path(sc, ln)
            if src.exists():
                dst = out / "audio" / src.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
    return tracks, errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", action="store_true", help="synthesize pilot audio (Gemini TTS, cached)")
    ap.add_argument(
        "--no-publish-audio", action="store_true", help="do not copy audio into app/public/data/scenarios"
    )
    ap.add_argument("--ids", default="", help="comma-separated scenario ids, default all")
    ap.add_argument("--check", action="store_true", help="validate only")
    ap.add_argument(
        "--prewarm",
        action="store_true",
        help="start the server and play every scenario once so the picker answers and the agent's TTS audio "
        "for every expected response are cached by the server's own render + TTS path",
    )
    args = ap.parse_args()

    if args.prewarm:
        import run  # imported lazily: it pulls in the speech stack

        with run.spawned_server() as base:
            run.warm(None, base)
        return
    scenarios = scn_model.load_all()
    want = [i.strip().upper() for i in args.ids.split(",") if i.strip()] or list(scenarios)
    all_errors: list[str] = []
    index = []
    manifest: dict[str, dict] = {}
    for sid in want:
        sc = scenarios[sid]
        if args.check:
            all_errors += scn_validate.validate(sc, scn_tracks.build_tracks(sc))
            continue
        _, errors = build_one(sc, args.audio, not args.no_publish_audio)
        all_errors += errors
        print(
            f"{sid}: {len(sc.aircraft)} aircraft, {len(sc.lines)} lines, {len(sc.events)} events"
            + (f", {len(errors)} validation error(s)" if errors else "")
        )
        for ln in sc.lines:
            manifest[f"{sid}/{ln.id}"] = scn_audio.manifest_entry(sc, ln)
        index.append(
            {
                "id": sid,
                "title": sc.title,
                "summary": sc.summary,
                "spec": sc.spec,
                "window_s": sc.window_s,
                "tracks": f"scenarios/{sid}/tracks.json",
                "lines": f"scenarios/{sid}/lines.json",
            }
        )
    if not args.check:
        paths.OUT_DIR.mkdir(parents=True, exist_ok=True)
        if set(want) == set(scenarios):
            (paths.OUT_DIR / "index.json").write_text(json.dumps({"scenarios": index}, indent=1) + "\n")
            (paths.HERE / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
        else:
            old = scn_audio.load_manifest(paths.HERE / "manifest.json")
            old.update(manifest)
            (paths.HERE / "manifest.json").write_text(json.dumps(old, indent=1, sort_keys=True) + "\n")
    if all_errors:
        print("VALIDATION ERRORS:")
        for e in all_errors:
            print("  -", e)
        raise SystemExit(1)
    print("ok")


if __name__ == "__main__":
    main()
