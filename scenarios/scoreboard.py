"""Aggregate results/*.json into SCOREBOARD.md and app/public/data/scenarios/scoreboard.json.

    uv run python scoreboard.py            # newest result per scenario, preferring runs with the server in the loop

JSON shape is documented in README.md ("scoreboard.json").
"""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime

import paths


def load_latest() -> dict[str, dict]:
    best: dict[str, dict] = {}
    for f in sorted(paths.RESULTS_DIR.glob("*.json")):
        r = json.loads(f.read_text())
        r["_file"] = f.name
        sid = r["scenario"]
        cur = best.get(sid)
        key = (bool(r["server"]["reachable"]), r["timestamp"])
        if cur is None or key > (bool(cur["server"]["reachable"]), cur["timestamp"]):
            best[sid] = r
    return best


def summarize(r: dict) -> dict:
    runs = r["runs"]
    last = runs[-1]
    agg = r["aggregate"]
    per = r["per_check"]
    checks = []
    for cid, v in sorted(per.items()):
        statuses = [
            next(
                (
                    c
                    for run in runs
                    for blk in (run["lines"], run["events"], [{"checks": run["summary_checks"]}])
                    for it in blk
                    for c in it["checks"]
                    if c["id"] == cid
                ),
                None,
            )
        ]
        c = statuses[0]
        checks.append(
            {
                "id": cid,
                "expected": c["expected"] if c else None,
                "actual": c["actual"] if c else None,
                "status": c["status"] if c else None,
                "passes": v["passes"],
                "runs": v["runs"],
                "pending": v["pending"],
                "gap": v.get("gap", 0),
                "stable": v["stable"],
            }
        )
    lat = [x for run in runs for x in run.get("auto_latencies", [])]
    server_ms = [x["server_ms"] for x in lat]
    speech_ms = [x["speech_ms"] for x in lat]
    outcomes = [ln.get("outcome") for ln in last["lines"]]
    handed = sum(1 for o in outcomes if o and o["mode"] == "handoff")
    return {
        "id": r["scenario"],
        "title": r["title"],
        "timestamp": r["timestamp"],
        "file": r["_file"],
        "mode": r["mode"],
        "server_in_loop": r["server"]["reachable"],
        "repeat": r["repeat"],
        "three_of_three": bool(agg["all_judged_passed_every_run"] and r["repeat"] >= 3),
        "all_judged_passed_every_run": agg["all_judged_passed_every_run"],
        "tally": last["tally"],
        "judged": agg["judged"],
        "pending_checks": agg["pending"],
        "counts": {
            "autonomous": sum(1 for o in outcomes if o and o["mode"] == "speak"),
            "approval_cards": sum(1 for o in outcomes if o and o["mode"] == "card"),
            "handed_off": handed,
            "silent": sum(1 for o in outcomes if o and o["mode"] in ("silent", "locked_silent")),
        },
        "latency_ms": {
            "server_median": round(statistics.median(server_ms)) if server_ms else None,
            "server_max": max(server_ms) if server_ms else None,
            "speech_median": round(statistics.median(speech_ms)) if speech_ms else None,
            "n_auto": len(server_ms),
        },
        "curation": r.get("curation"),
        "checks": checks,
    }


def table(rows: list[list[str]], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def verdict(s: dict) -> str:
    if s["three_of_three"]:
        return "3/3"
    if not s["server_in_loop"] and s["all_judged_passed_every_run"]:
        return f"{s['repeat']}/{s['repeat']} (dry run)"
    return "not passing"


def render(summaries: list[dict]) -> str:
    L = [
        "# Scenario scoreboard",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `scoreboard.py` from `scenarios/results/`. "
        "SIMULATION ONLY: fictional registrations, frequency shown as SIM DESK.",
        "",
        "Verdict `3/3` = every judged expectation matched in all 3 runs with the voice-agent server in the loop. "
        "`gap` = the expectation is known to be unimplemented in the server (reported, not counted as a failure). "
        "`pending` = could not be judged (no server).",
        "",
    ]
    rows = []
    for s in summaries:
        t = s["tally"]
        lat = s["latency_ms"]
        rows.append(
            [
                s["id"],
                s["title"],
                verdict(s),
                "yes" if s["server_in_loop"] else "no",
                t["pass"],
                t["fail"],
                t["partial"],
                t["gap"],
                t["pending"],
                s["counts"]["autonomous"],
                s["counts"]["approval_cards"],
                s["counts"]["handed_off"],
                f"{lat['server_median']} / {lat['server_max']}" if lat["n_auto"] else "n/a",
                f"{lat['speech_median']}" if lat["n_auto"] else "n/a",
            ]
        )
    L.append(
        table(
            rows,
            [
                "scenario",
                "title",
                "verdict",
                "server",
                "pass",
                "fail",
                "partial",
                "gap",
                "pending",
                "autonomous",
                "cards",
                "handed off",
                "server ms (median / max)",
                "ASR+parse ms",
            ],
        )
    )
    L.append("")
    L.append(
        "Latency columns cover auto-tier transmissions only. `server ms` is ParsedTransmission in -> agent audio "
        "ready (the issue #4 budget is 3000 ms); `ASR+parse ms` is Gemini ASR + the speech parser, on top of that."
    )
    L.append("")
    for s in summaries:
        L += [
            f"## {s['id']}: {s['title']}",
            "",
            f"{verdict(s)} | result file `{s['file']}` | ASR mode `{s['mode']}` | {s['repeat']} run(s)"
            + (f" | picker attempts to match: {s['curation']['attempts']}" if s.get("curation") else ""),
            "",
        ]
        rows = []
        for c in s["checks"]:
            short = c["id"].split(".", 1)[1]
            exp = json.dumps(c["expected"]) if not isinstance(c["expected"], str) else c["expected"]
            act = json.dumps(c["actual"]) if not isinstance(c["actual"], str) else c["actual"]
            rows.append(
                [
                    short,
                    (exp or "")[:60],
                    (act or "")[:60],
                    c["status"],
                    f"{c['passes']}/{c['runs']}"
                    + (f" (+{c['pending']} pending)" if c["pending"] and c["passes"] < c["runs"] else ""),
                ]
            )
        L.append(table(rows, ["expectation", "expected", "actual (last run)", "status", "passed"]))
        L.append("")
    return "\n".join(L) + "\n"


def main() -> None:
    latest = load_latest()
    order = ["S1", "S2", "S3A", "S3B", "S4", "S5", "S6"]
    summaries = [summarize(latest[i]) for i in order if i in latest]
    (paths.HERE / "SCOREBOARD.md").write_text(render(summaries))
    totals = {
        "scenarios": len(summaries),
        "three_of_three": sum(s["three_of_three"] for s in summaries),
        "judged_pass": sum(s["tally"]["pass"] for s in summaries),
        "judged_fail": sum(s["tally"]["fail"] + s["tally"]["partial"] for s in summaries),
        "gaps": sum(s["tally"]["gap"] for s in summaries),
        "pending": sum(s["tally"]["pending"] for s in summaries),
    }
    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "simulation": True,
        "totals": totals,
        "scenarios": summaries,
    }
    paths.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (paths.OUT_DIR / "scoreboard.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote SCOREBOARD.md and scoreboard.json: {totals}")


if __name__ == "__main__":
    main()
