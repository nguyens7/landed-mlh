"""Run-to-run agreement: Gemini template picker vs the Decisions router, N runs per input.

Usage (keys in the environment only, see server/scripts/with_openai_key.sh):
    server/scripts/with_openai_key.sh uv run --project agent python agent/scripts/measure_agreement.py \
        [--runs 10] [--out agent/AGREEMENT.md]

Inputs: every pilot line in scenarios/*.yaml if present, else speech/scripts/utterances.yaml (read-only).
Cache is OFF. The Gemini picker uses its own call built here (temperature 0, fixed seed, pinned model) because
gemini_agent.gemini_model_call does not expose a seed; it reuses gemini_agent.SYSTEM and TOOLS unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

from landed_agent import gemini_agent as G
from landed_agent.desk import DeskState
from landed_agent.models import AdsbPosition, Callsign, ParsedTransmission, Slots
from landed_agent.policy import evaluate
from landed_agent.router import DecisionsRouter, GeminiEnumRouter, JevRouter

ROOT = Path(__file__).resolve().parents[2]
ROSTER = ["N2646X", "N312LM", "N405LP"]
SEED = 7
PICKER_MODEL = G.DEFAULT_MODEL
DECISIONS_TIMEOUT_S = 10.0  # measure true latency; the production timeout is 0.8 s


def load_inputs() -> tuple[list[dict[str, Any]], str]:
    files = sorted((ROOT / "scenarios").glob("*.yaml")) if (ROOT / "scenarios").exists() else []
    if files:
        rows: list[dict[str, Any]] = []
        for f in files:
            data = yaml.safe_load(f.read_text())
            rows += data if isinstance(data, list) else []
        if rows and all("text" in r for r in rows):
            return rows, "scenarios/*.yaml"
    return yaml.safe_load(
        (ROOT / "speech/scripts/utterances.yaml").read_text()
    ), "speech/scripts/utterances.yaml"


def build(row: dict[str, Any]) -> tuple[ParsedTransmission, DeskState]:
    cs = row.get("callsign") or {}
    amb = bool(cs.get("ambiguous"))
    slots = Slots(**{k: v for k, v in (row.get("slots") or {}).items() if k in Slots.model_fields})
    parsed = ParsedTransmission(
        raw_text=row["text"],
        asr_confidence=0.95,
        callsign=Callsign(
            spoken=None,
            normalized=cs.get("normalized"),
            snapped_to=cs.get("snapped_to"),
            snap_score=0.6 if amb else 0.95,
            ambiguous_with=["N2464X"] if amb else [],
        ),
        intent=row.get("intent", "unknown"),
        slots=slots,
        emergency=bool(row.get("emergency")),
        parse_confidence=0.97,
        reason="measurement fixture",
    )
    desk = DeskState(
        roster=list(ROSTER),
        traffic=[{"clock": 3, "distance_nm": 2.0, "traffic_type": "helicopter", "altitude_ft": 700}],
    )
    desk.positions["N2646X"] = AdsbPosition(reg="N2646X", lat=40.7013, lon=-74.0085, alt_ft=400)
    return parsed, desk


def picker_call(model: str, client: Any):
    from google.genai import types

    def call(prompt: str) -> dict[str, Any] | None:
        cfg = types.GenerateContentConfig(
            system_instruction=G.SYSTEM,
            tools=[types.Tool(function_declarations=G.TOOLS)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.ANY)
            ),
            temperature=0.0,
            seed=SEED,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        )
        resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
        calls = resp.function_calls or []
        return {"name": calls[0].name, "args": dict(calls[0].args or {})} if calls else None

    return call


def canon(x: Any) -> str:
    return json.dumps(x, sort_keys=True, default=str)


def summarize(per_input: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(per_input)
    lat = sorted(x for r in per_input for x in r["lat"])
    dist = Counter(len(set(r["full"])) for r in per_input)
    pct = lambda k: round(100 * sum(1 for r in per_input if len(set(r[k])) == 1) / n, 1)  # noqa: E731
    return {
        "n": n,
        "agree_id": pct("id"),
        "agree_slots": pct("slots"),
        "agree_full": pct("full"),
        "distinct": dict(sorted(dist.items())),
        "p50": round(statistics.median(lat)),
        "p95": round(lat[int(0.95 * (len(lat) - 1))]),
        "over_800": round(100 * sum(1 for x in lat if x > 800) / len(lat), 1),
        "errors": sum(r["errors"] for r in per_input),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "agent/AGREEMENT.md"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    rows, src = load_inputs()
    if args.limit:
        rows = rows[: args.limit]
    cases = [(r["id"], *build(r)) for r in rows]

    results: dict[str, Any] = {}
    # ---- Gemini template picker (only inputs the policy would hand to the model)
    if os.environ.get("GEMINI_API_KEY"):
        from google import genai

        call = picker_call(PICKER_MODEL, genai.Client(api_key=os.environ["GEMINI_API_KEY"]))
        pick_cases = [
            (i, p, d)
            for i, p, d in cases
            if evaluate(p, d).forced_template is None and evaluate(p, d).tier in ("auto", "approval")
        ]

        def run_pick(case):
            i, p, d = case
            dec = evaluate(p, d)
            ids, sl, full, lat, err = [], [], [], [], 0
            for _ in range(args.runs):
                t0 = time.perf_counter()
                c = G.choose(p, d, dec, call)
                lat.append((time.perf_counter() - t0) * 1000)
                key_id = c.template_id.value if c.template_id else c.kind
                err += c.source == "fallback"
                ids.append(key_id)
                sl.append(canon(c.slots))
                full.append(key_id + canon(c.slots))
            return {"id_": i, "id": ids, "slots": sl, "full": full, "lat": lat, "errors": err}

        with ThreadPoolExecutor(8) as ex:
            results["picker"] = summarize(list(ex.map(run_pick, pick_cases)))
        results["picker"]["inputs"] = len(pick_cases)

    # ---- routers: label + rounded probability agreement
    def run_router(make):
        def f(case):
            i, p, d = case
            r = make()
            outs, lat, err = [], [], 0
            for _ in range(args.runs):
                t0 = time.perf_counter()
                o = r.route(p, d)
                lat.append((time.perf_counter() - t0) * 1000)
                err += o.abstained
                outs.append(o)
            return {
                "id_": i,
                "id": [o.label for o in outs],
                "slots": [f"{o.label_p:.2f}/{o.attention_p:.2f}" for o in outs],
                "full": [f"{o.label}|{o.label_p:.4f}|{o.attention_p:.4f}|{o.abstained}" for o in outs],
                "lat": lat,
                "errors": err,
                "reasons": sorted({o.reason for o in outs if o.abstained}),
            }

        return f

    if os.environ.get("OPENAI_API_KEY"):
        with ThreadPoolExecutor(8) as ex:
            rows_d = list(
                ex.map(run_router(lambda: DecisionsRouter(timeout_s=DECISIONS_TIMEOUT_S, cache=False)), cases)
            )
        results["decisions"] = summarize(rows_d)
        results["decisions"]["reasons"] = sorted({x for r in rows_d for x in r["reasons"]})
    if os.environ.get("TYPESAFE_API_KEY"):
        with ThreadPoolExecutor(8) as ex:
            rows_j = list(ex.map(run_router(lambda: JevRouter(timeout_s=10.0, cache=False)), cases))
        results["jev"] = summarize(rows_j)
        results["jev"]["reasons"] = sorted({x for r in rows_j for x in r["reasons"]})
    if os.environ.get("GEMINI_API_KEY"):
        with ThreadPoolExecutor(8) as ex:
            rows_g = list(ex.map(run_router(lambda: GeminiEnumRouter(timeout_s=10.0, cache=False)), cases))
        results["gemini_enum"] = summarize(rows_g)
        results["gemini_enum"]["reasons"] = sorted({x for r in rows_g for x in r["reasons"]})

    Path(args.out).write_text(render_md(results, src, len(cases), args.runs))
    print(json.dumps(results, indent=1), file=sys.stderr)


def default_note(res: dict[str, Any]) -> str:
    """Rule: among routers whose p95 is under 800 ms, pick the highest label agreement, then full-output agreement."""
    names = {"decisions": "decisions", "jev": "jev", "gemini_enum": "gemini"}
    ok = {k: v for k, v in res.items() if k in names and v["p95"] < 800}
    if not ok:
        return "No router had p95 under 800 ms in this run, so no router is recommended as the default by this rule; every call over the 800 ms production timeout abstains to the approval card."
    best = max(ok, key=lambda k: (ok[k]["agree_id"], ok[k]["agree_full"], -ok[k]["p95"]))
    return (
        f"Rule: highest label agreement among routers with p95 under 800 ms. Winner: `{names[best]}` "
        f"(label agreement {ok[best]['agree_id']}%, full-output agreement {ok[best]['agree_full']}%, p95 {ok[best]['p95']} ms). "
        "Select with `LANDED_ROUTER=decisions|jev|gemini`. Thresholds are provisional until validated on our own labeled data."
    )


def render_md(res: dict[str, Any], src: str, n: int, runs: int) -> str:
    def row(name: str, r: dict[str, Any], a: str, b: str) -> str:
        return (
            f"| {name} | {r['n']} | {r['agree_id']}% | {r['agree_slots']}% | {r['agree_full']}% | "
            f"{r['distinct']} | {r['p50']} / {r['p95']} | {r['over_800']}% | {r['errors']} |"
        )

    lines = [
        "# Run-to-run agreement",
        "",
        f"Inputs: {n} pilot lines from `{src}` (read-only). Each input is sent {runs} times per provider with every",
        "demo cache OFF. Agreement means all runs returned the same value. This measures the *service*, not a",
        "claim of determinism: neither vendor documents determinism.",
        "",
        "| Provider | Inputs | All runs agree: id / label | slots / label prob + attention | full output | Distinct full outputs (count: inputs) | Latency ms p50 / p95 | Calls over 800 ms | Fallbacks or abstentions |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    if "picker" in res:
        lines.append(row(f"Gemini template picker ({PICKER_MODEL})", res["picker"], "", ""))
    if "decisions" in res:
        lines.append(row("OpenAI Decisions router (gpt-6-luna)", res["decisions"], "", ""))
    if "jev" in res:
        lines.append(row("TypeSafe Jev router (jev-latest)", res["jev"], "", ""))
    if "gemini_enum" in res:
        lines.append(
            row(
                f"Gemini enum router ({res['gemini_enum'] and 'gemini-3.5-flash-lite'})",
                res["gemini_enum"],
                "",
                "",
            )
        )
    lines += [
        "",
        "Picker rows count `template_id` (or `handoff`) and the validated slot dict; router rows count the label,",
        "the label probability and attention probability rounded to 2 decimals (slots column) or 4 decimals",
        "(full output column). The picker is measured only on inputs the policy would hand to the model",
        f"({res.get('picker', {}).get('inputs', 'n/a')} of {n}); policy-forced inputs never reach it.",
        "",
        "## Settings",
        "",
        f"- Gemini picker: model `{PICKER_MODEL}`, `temperature=0.0`, `seed={SEED}`, `thinking_level=low`, forced function calling",
        "  (`mode=ANY`), prompt and tools from `gemini_agent.SYSTEM` / `TOOLS` unchanged, cache OFF. The seed is passed from",
        "  `measure_agreement.py` because `gemini_agent.gemini_model_call` does not expose one (not edited).",
        "- Decisions router: `POST /v1/decisions`, model `gpt-6-luna`, a `choice` over 4 labels plus a `predicate`,",
        f"  client timeout {DECISIONS_TIMEOUT_S:.0f} s for the measurement (production timeout is 800 ms), cache OFF.",
        "  The Decisions API exposes no temperature or seed.",
        f"- Gemini enum router: `gemini-3.5-flash-lite`, `temperature=0`, `seed={SEED}`, JSON schema with an enum label.",
        "  Its probabilities are self-reported by the model, not calibrated.",
        "- Jev router: `POST /v1/systemone`, model `jev-latest`, a `choice` over 4 labels plus a `noul`, client timeout 10 s for the measurement, cache OFF. No temperature or seed is exposed.",
        "- Desk state: roster N2646X / N312LM / N405LP, altimeter 29.92, one traffic entry, N2646X on ADS-B at JRB,",
        "  ASR 0.95, parse 0.97, callsign snap 0.95 (0.60 and ambiguous when the bank marks it ambiguous).",
        "",
    ]
    lines += ["", "## Default router", "", default_note(res), ""]
    for k in ("decisions", "jev", "gemini_enum"):
        if res.get(k, {}).get("reasons"):
            lines.append(f"Abstention reasons seen for {k}: {', '.join(res[k]['reasons'])}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
