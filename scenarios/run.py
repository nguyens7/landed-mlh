"""Scenario runner: play S1-S6, record actual outcomes, compare with the expected ones in the YAML.

    uv run python run.py --all --spawn-server --repeat 3     # start the server, run every scenario 3x
    uv run python run.py S1 --server http://127.0.0.1:8787   # against a server you started yourself
    uv run python run.py --all --dry-run                     # speech + engine only; server checks "pending server"
    uv run python run.py S4 --mode refresh                   # re-run Gemini ASR on the audio and re-pin the results
    uv run python run.py S4 --mode live --fresh-asr --repeat 3   # ASR stability probe (bypasses the ASR cache)

For each line: audio -> ASR -> speech parser (speech/) -> adapter -> server. For each geometry event:
scn_engine / scn_checks on the generated track -> adapter -> server. Results go to
results/<id>-<timestamp>.json (all runs, aggregate, 3/3 verdict) and .log (the expected-vs-actual log).
Run scoreboard.py afterwards to refresh SCOREBOARD.md and scoreboard.json.

Determinism: ASR + parse come from committed pins (pins/asr_pins.json). The server's Gemini template picker runs
at temperature 0 and caches every answer on disk keyed by (model, system prompt, prompt); --spawn-server points
LANDED_CACHE_DIR at scenarios/server_cache so those answers are committed and replays are identical.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime

import paths  # sys.path for replay/ and speech/ must be set up first

# isort: split
from landed_geo import great_circle_bearing, great_circle_dist_nm

import scn_events
import scn_model
import scn_pipeline
import scn_tracks
from adapter import ServerAdapter
from scn_model import Scenario
from scoring import Check, RunScore, score_parse, score_response, status_of, three_of_three

SPAWN_PORT = 8787
SERVER_CACHE = paths.HERE / "server_cache"
SPOKEN_MODES = ("speak", "handoff")


def _fmt(v) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= 90 else s[:87] + "..."


def check_line(c: Check) -> str:
    tag = {"pass": "PASS", "fail": "FAIL", "partial": "PART", "pending": "PEND", "gap": "GAP "}[c.status]
    extra = f"  ({c.detail})" if c.detail else ""
    return f"      {tag}  {c.id.split('.', 1)[1]:<34} expected {_fmt(c.expected)}  actual {_fmt(c.actual)}{extra}"


# ------------------------------------------------------------------ server session helpers
def _llm_files() -> set[str]:
    d = SERVER_CACHE / "llm"
    return {p.name for p in d.glob("*.json")} if d.exists() else set()


def traffic_for(tracks: dict, reg: str, t: float) -> list[dict]:
    """Nearest non-desk aircraft as the server's TRAFFIC data: clock position, miles, type, altitude (hundreds)."""
    me = next(a for a in tracks["aircraft"] if a["reg"] == reg)
    p0 = scn_tracks.position_at(me, t)
    if p0 is None:
        return []
    trk = next((p["track_deg"] for p in reversed(me["points"]) if p["t"] <= t), me["points"][0]["track_deg"])
    best = None
    for o in tracks["aircraft"]:
        if o.get("desk", True):
            continue
        p1 = scn_tracks.position_at(o, t)
        if p1 is None:
            continue
        d = great_circle_dist_nm(p0[0], p0[1], p1[0], p1[1])
        if d <= 6 and (best is None or d < best[0]):
            rel = (great_circle_bearing(p0[0], p0[1], p1[0], p1[1]) - trk) % 360
            best = (d, rel, p1[2])
    if not best:
        return []
    d, rel, alt = best
    clock = int(round(rel / 30)) % 12 or 12
    return [
        {
            "clock": clock,
            "distance_nm": max(0.5, round(d * 2) / 2),
            "traffic_type": "helicopter",
            "altitude_ft": int(round(alt / 100) * 100),
        }
    ]


class Desk:
    """Keeps the server's desk in step with the scenario: roster in check-in order, traffic, ADS-B positions."""

    def __init__(self, adapter: ServerAdapter, tracks: dict) -> None:
        self.adapter, self.tracks = adapter, tracks
        self.roster: list[str] = []
        self.traffic: list[dict] = []

    def sync(self, reg: str, t: float) -> None:
        traffic = traffic_for(self.tracks, reg, t)
        if reg not in self.roster or (
            traffic != self.traffic and any(not a.get("desk", True) for a in self.tracks["aircraft"])
        ):
            if reg not in self.roster:
                self.roster.append(reg)
            self.traffic = traffic
            self.adapter.set_desk([reg], 29.92, traffic, merge=True)
        for a in self.tracks["aircraft"]:
            if a["reg"] not in self.roster:
                continue
            p = scn_tracks.position_at(a, t)
            if p is not None:
                self.adapter.adsb(a["reg"], p[0], p[1], p[2], scn_tracks.squawk_at(a, t))


# ------------------------------------------------------------------ one run
def summary_checks(sc: Scenario, outcomes: list[tuple[str, float, dict | None]]) -> list[Check]:
    exp = sc.expected_summary
    judged = bool(outcomes) and all(o is not None for _, _, o in outcomes)
    spoken = [(r, t, o) for r, t, o in outcomes if o and o["mode"] in SPOKEN_MODES]
    lock_t = next((t for _, t, o in outcomes if o and o["template_id"] == "CONTROLLER_TAKING_OVER"), None)
    actual = {
        "transmissions": len(spoken),
        "auto_transmissions": sum(1 for _, _, o in outcomes if o and o["mode"] == "speak"),
        "handoffs": len(
            {
                r
                for r, _, o in outcomes
                if o and o["mode"] == "handoff" and o["template_id"] != "CONTROLLER_TAKING_OVER"
            }
        ),
        "cards": sum(1 for _, _, o in outcomes if o and o["mode"] == "card"),
        "transmissions_after_lock": sum(1 for _, t, _ in spoken if lock_t is not None and t > lock_t),
    }
    out = []
    for name, got in actual.items():
        want = getattr(exp, name)
        if want is None:
            continue
        cid = f"{sc.id}.summary.{name}"
        out.append(
            Check(
                cid,
                name,
                want,
                got if judged else None,
                ("pass" if got == want else "fail") if judged else "pending",
                "" if judged else "pending server",
            )
        )
    return out


def play(
    sc: Scenario,
    tracks: dict,
    mode: str,
    adapter: ServerAdapter | None,
    pins: dict,
    decide: str | None,
    fresh_asr: bool,
    run_no: int,
) -> dict:
    desk: Desk | None = None
    if adapter:
        adapter.reset()
        desk = Desk(adapter, tracks)
    evals = scn_events.evaluate(sc, tracks, {ln.id: ln.t for ln in sc.lines})
    timeline: list[tuple[float, int, str, object]] = [(ln.t, 0, "line", ln) for ln in sc.lines]
    timeline += [(e.t if e.event.kind != "no_alerts" else sc.window_s + 1, 1, "event", e) for e in evals]
    timeline.sort(key=lambda x: (x[0], x[1]))

    score = RunScore()
    log: list[str] = []
    line_out: list[dict] = []
    event_out: list[dict] = []
    outcomes: list[tuple[str, float, dict | None]] = []
    latencies: list[dict] = []
    for _t, _, kind, obj in timeline:
        if kind == "line":
            ln = obj
            h = scn_pipeline.hear(sc, ln, mode=mode, pins=pins, fresh=fresh_asr)
            checks = score_parse(f"{sc.id}.{ln.id}", ln.expect.parse, h.parsed, h.asr_confidence)
            reply = None
            new_files: list[str] = []
            if adapter and desk:
                desk.sync(ln.aircraft, ln.t)
                before = _llm_files()
                reply = adapter.post_transmission(h.parsed)
                new_files = sorted(_llm_files() - before)
            outcome = reply.outcome if reply and reply.ok else None
            speech_ms = ((h.asr_latency_s or 0) + (h.parse_latency_s or 0)) * 1000
            total_ms = speech_ms + (reply.latency_ms or 0) if reply and reply.ok else None
            checks += score_response(
                f"{sc.id}.{ln.id}",
                ln.expect.response,
                outcome,
                reply.latency_ms if reply and reply.ok else None,
            )
            outcomes.append((ln.aircraft, ln.t, outcome))
            if outcome and decide and outcome["mode"] == "card" and outcome["proposal_id"]:
                adapter.decide(outcome["proposal_id"], decide)
            if outcome and outcome["mode"] in SPOKEN_MODES and outcome["tier"] == "auto":
                latencies.append(
                    {
                        "line": ln.id,
                        "speech_ms": round(speech_ms),
                        "server_ms": round(reply.latency_ms or 0),
                        "total_ms": round(total_ms or 0),
                        "source": outcome["source"],
                    }
                )
            score.add(checks)
            line_out.append(
                {
                    "id": ln.id,
                    "t": ln.t,
                    "aircraft": ln.aircraft,
                    "text": ln.text,
                    "picker_cache": new_files,
                    "heard": {
                        "text": h.text,
                        "asr_confidence": h.asr_confidence,
                        "source": h.source,
                        "parsed": h.parsed,
                        "asr_latency_s": h.asr_latency_s,
                        "parse_latency_s": h.parse_latency_s,
                    },
                    "outcome": ({k: v for k, v in outcome.items() if k != "extras"} if outcome else None),
                    "server_error": reply.error if reply and not reply.ok else None,
                    "speech_latency_ms": round(speech_ms),
                    "total_latency_ms": round(total_ms) if total_ms else None,
                    "status": status_of(checks),
                    "checks": [c.to_dict() for c in checks],
                }
            )
            log.append(f"t={ln.t:<6} {ln.id}  {ln.aircraft}  [{status_of(checks).upper()}]")
            log.append(f"      said  : {ln.text}")
            log.append(
                f"      heard : {h.text}   (asr {h.asr_confidence if h.asr_confidence is None else round(h.asr_confidence, 2)}, "
                f"{h.parsed['parser']} parser, {h.source})"
            )
            if outcome:
                log.append(
                    f"      agent : {outcome['mode']} {outcome['template_id']} tier={outcome['tier']} "
                    f'triggers={outcome["triggers"]} src={outcome["source"]}  "{outcome["spoken_text"] or ""}"'
                )
            elif reply and not reply.ok:
                log.append(f"      server error: {reply.error}")
            log += [check_line(c) for c in checks]
        else:
            ev: scn_events.EventEval = obj
            checks = list(ev.checks)
            outcome = None
            wants = ev.event.response
            if (
                adapter
                and desk
                and (ev.alert is not None)
                and (wants.mode or wants.template_id or wants.triggers)
            ):
                reg = ev.event.aircraft or ""
                desk.sync(reg, ev.t) if reg in desk.roster else None
                if ev.event.kind == "squawk":
                    p = scn_tracks.position_at(next(a for a in tracks["aircraft"] if a["reg"] == reg), ev.t)
                    reply = adapter.adsb(reg, p[0], p[1], p[2], ev.event.code)
                else:
                    reply = adapter.post_alerts(
                        [
                            {
                                k: v
                                for k, v in ev.alert.items()
                                if k
                                in (
                                    "id",
                                    "aircraft",
                                    "volume_id",
                                    "severity",
                                    "confidence",
                                    "reason",
                                    "time_to_entry_s",
                                    "entry_point",
                                    "entry_alt_ft",
                                )
                            }
                            | ({"time_to_entry_s": ev.alert.get("time_to_entry_s", 90)})
                        ]
                    )
                outcome = reply.outcome if reply.ok else None
                outcomes.append((reg, ev.t, outcome))
                checks += score_response(
                    f"{sc.id}.{ev.event.id}", wants, outcome, reply.latency_ms if reply.ok else None
                )
            elif ev.alert is not None and (wants.mode or wants.template_id or wants.triggers):
                checks += score_response(f"{sc.id}.{ev.event.id}", wants, None)
            for c in checks:
                if not c.id.startswith(sc.id + "."):
                    c.id = f"{sc.id}.{c.id}"
            score.add(checks)
            event_out.append(
                {
                    "id": ev.event.id,
                    "kind": ev.event.kind,
                    "t": ev.t,
                    "facts": ev.facts,
                    "alert": ev.alert,
                    "outcome": ({k: v for k, v in outcome.items() if k != "extras"} if outcome else None),
                    "status": status_of(checks),
                    "checks": [c.to_dict() for c in checks],
                }
            )
            log.append(f"t={ev.t:<6} {ev.event.id}  event:{ev.event.kind}  [{status_of(checks).upper()}]")
            if outcome:
                log.append(
                    f"      agent : {outcome['mode']} {outcome['template_id']} tier={outcome['tier']} "
                    f'triggers={outcome["triggers"]}  "{outcome["spoken_text"] or ""}"'
                )
            log += [check_line(c) for c in checks]
    sc_checks = summary_checks(sc, outcomes if adapter else [])
    score.add(sc_checks)
    if sc_checks:
        log.append("summary")
        log += [check_line(c) for c in sc_checks]
    return {
        "run": run_no,
        "status": score.status,
        "tally": score.tally,
        "lines": line_out,
        "events": event_out,
        "summary_checks": [c.to_dict() for c in sc_checks],
        "auto_latencies": latencies,
        "log": "\n".join(log),
        "_checks": score.checks,
    }


# ------------------------------------------------------------------ server lifecycle
@contextlib.contextmanager
def spawned_server(port: int = SPAWN_PORT):
    """Start the real server (Gemini key from Secret Manager, env only) with scenario-local caches."""
    env = {**os.environ, "LANDED_CACHE_DIR": str(SERVER_CACHE)}
    cmd = [
        str(paths.REPO / "server" / "scripts" / "with_gemini_key.sh"),
        "uv",
        "run",
        "--project",
        "server",
        "uvicorn",
        "landed_server.app:app",
        "--port",
        str(port),
    ]
    proc = subprocess.Popen(
        cmd, cwd=paths.REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    base = f"http://127.0.0.1:{port}"
    try:
        probe = ServerAdapter(base, timeout_s=2.0)
        for _ in range(90):
            if probe.available():
                break
            if proc.poll() is not None:
                raise SystemExit("server exited during startup")
            time.sleep(1)
        else:
            raise SystemExit("server did not come up in 90 s")
        yield base
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(10)


def run_batch(want: list[str], args, base_url: str | None) -> int:
    scenarios = scn_model.load_all()
    adapter: ServerAdapter | None = None
    if base_url and not args.dry_run:
        a = ServerAdapter(base_url)
        adapter = a if a.available() else None
        print(
            f"server {base_url}: {'reachable' if adapter else 'NOT reachable -> server checks are pending'}"
        )
    else:
        print("dry run: server not called; server checks are pending server")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    paths.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    pins = scn_pipeline.load_pins()
    exit_code = 0
    if (
        getattr(args, "curate", False) and adapter
    ):  # rebuild the picker cache from scratch so each entry is attributable
        for f in (SERVER_CACHE / "llm").glob("*.json"):
            f.unlink()
    for sid in want:
        sc = scenarios[sid]
        tracks = scn_tracks.build_tracks(sc)
        runs = []
        curation = None
        t0 = time.time()
        if getattr(args, "curate", False) and adapter:
            curation = curate(sc, tracks, args, adapter, pins)
        for n in range(1, args.repeat + 1):
            runs.append(play(sc, tracks, args.mode, adapter, pins, args.decide, args.fresh_asr, n))
        agg = three_of_three([r["_checks"] for r in runs])
        for r in runs:
            r.pop("_checks")
        result = {
            "scenario": sid,
            "title": sc.title,
            "timestamp": stamp,
            "mode": args.mode,
            "dry_run": adapter is None,
            "server": {
                "url": base_url,
                "reachable": adapter is not None,
                "context_pushed": bool(adapter and adapter.context_pushed),
            },
            "repeat": args.repeat,
            "curation": curation,
            "runs": runs,
            "aggregate": {k: v for k, v in agg.items() if k != "checks"},
            "per_check": agg["checks"],
            "wall_s": round(time.time() - t0, 2),
        }
        base = paths.RESULTS_DIR / f"{sid}-{stamp}"
        base.with_suffix(".json").write_text(json.dumps(result, indent=1, default=str) + "\n")
        header = f"{sid}  {sc.title}\nmode={args.mode} server={'yes' if adapter else 'no (dry run)'} repeat={args.repeat}  {stamp}\n"
        body = "\n\n".join(
            f"--- run {r['run']}/{args.repeat}: {r['status'].upper()} {r['tally']}\n{r['log']}" for r in runs
        )
        base.with_suffix(".log").write_text(header + "\n" + body + "\n")
        t = runs[-1]["tally"]
        ok = agg["all_judged_passed_every_run"]
        verdict = f"{args.repeat}/{args.repeat}" if ok else "NOT passing"
        print(
            f"{sid:<4} {verdict:<12} pass={t['pass']} fail={t['fail']} partial={t['partial']} gap={t['gap']} "
            f"pending={t['pending']} of {t['total']}  -> {base.with_suffix('.log').relative_to(paths.HERE)}"
        )
        if not ok:
            exit_code = 1
    return exit_code


def picker_miss(run: dict) -> list[str]:
    """Lines whose picker answer (Gemini or its fallback) did not give the expected response."""
    out = []
    for i in run["lines"] + run["events"]:
        src = (i.get("outcome") or {}).get("source")
        bad = any(c["status"] == "fail" and ".response." in c["id"] for c in i["checks"])
        if src == "fallback" or (src == "gemini" and bad):
            out.append(f"{i['id']}")
    return out


def curate(sc: Scenario, tracks: dict, args, adapter: ServerAdapter, pins: dict, attempts: int = 6) -> dict:
    """The picker (Gemini, temperature 0) can still return an invalid answer, and the server caches it. Replay the
    scenario; whenever any call fell back, delete the picker cache entries written during that attempt and retry,
    so the committed cache holds only answers that rendered a valid template."""
    llm_dir = SERVER_CACHE / "llm"
    history: list[list[str]] = []
    for n in range(1, attempts + 1):
        time.time() - 1
        r = play(sc, tracks, args.mode, adapter, pins, None, False, 0)
        miss = picker_miss(r)
        history.append(miss)
        if not miss:
            print(f"  {sc.id}: picker answers match after {n} attempt(s)")
            return {"attempts": n, "misses_before": history[:-1]}
        for i in r["lines"] + r["events"]:
            if i["id"] in miss:
                for name in i.get("picker_cache", []):
                    (llm_dir / name).unlink(missing_ok=True)
        print(f"  {sc.id}: picker missed {miss} on attempt {n}; cleared its cache entries and retrying")
    print(f"  {sc.id}: picker still missing {history[-1]} after {attempts} attempts (kept the last answers)")
    return {"attempts": attempts, "misses_before": history}


def warm(ids: list[str] | None = None, base_url: str | None = None) -> None:
    """Play every scenario once against the server so the LLM pick and the agent's TTS audio for every expected
    response are cached by the server's own render + TTS path (used by build.py --prewarm)."""
    ns = argparse.Namespace(repeat=1, mode="pinned", dry_run=False, decide=None, fresh_asr=False)
    scenarios = scn_model.load_all()
    run_batch(ids or list(scenarios), ns, base_url)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="scenario ids (S1 S2 S3A S3B S4 S5 S6)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--mode", choices=["pinned", "live", "refresh"], default="pinned")
    ap.add_argument("--dry-run", action="store_true", help="speech + engine only; never call the server")
    ap.add_argument("--server", default=f"http://127.0.0.1:{SPAWN_PORT}")
    ap.add_argument(
        "--spawn-server", action="store_true", help="start the server (Gemini key from Secret Manager)"
    )
    ap.add_argument(
        "--decide",
        choices=["approve", "reject"],
        default=None,
        help="answer approval cards via POST /decision (default: leave them pending)",
    )
    ap.add_argument(
        "--curate",
        action="store_true",
        help="re-ask the picker until no call falls back (fills server_cache)",
    )
    ap.add_argument(
        "--fresh-asr", action="store_true", help="bypass the ASR cache on every call (stability probe)"
    )
    args = ap.parse_args()
    scenarios = scn_model.load_all()
    want = list(scenarios) if args.all or not args.ids else [i.upper() for i in args.ids]
    if args.spawn_server and not args.dry_run:
        with spawned_server() as base:
            raise SystemExit(run_batch(want, args, base))
    raise SystemExit(run_batch(want, args, args.server))


if __name__ == "__main__":
    main()
