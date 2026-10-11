"""Evaluate ASR + parsing on the synthetic radio bank and on real ATCO2 audio -> RESULTS.md.

    uv run python eval.py --asr gemini     # primary ASR = Gemini (default); OpenAI shown from cache if present
    uv run python eval.py --asr openai     # primary ASR = OpenAI (cache only; no new OpenAI calls)
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jiwer

from asr import GEMINI_ASR_MODEL, GENERIC_PROMPT, OPENAI_ASR_MODEL, CacheMiss, nyc_prompt, transcribe
from bank import (
    SLOT_NAMES,
    callsign_exact,
    callsign_safe,
    callsign_snapped,
    critical_error,
    load_bank,
    pred_slots,
    slot_diffs,
    truth_slots,
)
from keys import ensure_gemini_key
from normalize import collapse_mixed, group_runs, is_letter_token, lex, normalize_for_wer
from parse import LLM_MODEL, last_llm_latency, llm_raw, parse_transmission

ROOT = Path(__file__).parent
SNR_ORDER = ["clean", "20", "10", "5", "0", "-5"]
THRESHOLDS = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98]
RECALL_TARGET = 0.65


# ------------------------------------------------------------------ helpers
def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def corpus_wer(refs: list[str], hyps: list[str]) -> float | None:
    if not refs:
        return None
    o = jiwer.process_words(refs, hyps)
    return (o.substitutions + o.deletions + o.insertions) / max(1, sum(len(r.split()) for r in refs))


def clip_wer(ref: str, hyp: str) -> float:
    r, h = normalize_for_wer(ref), normalize_for_wer(hyp)
    if not r:
        return 0.0 if not h else 1.0
    return jiwer.wer(r, h or "x") if h else 1.0


def auroc(pos: list[float], neg: list[float]) -> float | None:
    """P(score of a 'good' item > score of a 'bad' item); ties count half."""
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None

    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    rx, ry = rank(x), rank(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def fmt(x: float | None, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


# ------------------------------------------------------------------ synthetic runs
def run_set(manifest: list[dict], backend: str, resamples: int = 2, model: str = GEMINI_ASR_MODEL,
            prompt: str | None = None) -> list[dict]:
    def run(m: dict) -> dict | None:
        try:
            asr = transcribe(ROOT / m["file"], backend=backend, resamples=resamples, model=model, prompt=prompt)
        except CacheMiss:
            return None
        gt = m["ground_truth"]
        item = {"callsign": gt["callsign"], "intent": gt["intent"], "emergency": gt["emergency"],
                "slots": {**{k: None for k in SLOT_NAMES}, **gt["slots"]}}
        t0 = time.perf_counter()
        pt_gram = parse_transmission(asr.text, asr.confidence, llm=False)
        t_gram = time.perf_counter() - t0
        pt_final = parse_transmission(asr.text, asr.confidence, llm=True)
        llm_lat = last_llm_latency()
        return {"m": m, "item": item, "asr": asr, "final": pt_final, "grammar": pt_gram,
                "pipeline_s": t_gram + (llm_lat or 0.0), "llm_called": llm_lat is not None}

    with ThreadPoolExecutor(16) as ex:
        return [r for r in ex.map(run, manifest) if r is not None]


def synth_metrics(rows: list[dict], key: str = "final") -> dict:
    n = len(rows)
    refs = [normalize_for_wer(r["m"]["ground_truth"]["text"]) for r in rows]
    hyps = [normalize_for_wer(r["asr"].text) for r in rows]
    tp = fn = 0
    exact = []
    for r in rows:
        t, p = truth_slots(r["item"]), pred_slots(r[key])
        for k in SLOT_NAMES:
            if t[k] is not None:
                tp += t[k] == p[k]
                fn += t[k] != p[k]
        exact.append(not slot_diffs(r["item"], r[key]))
    emerg_truth = [r for r in rows if r["item"]["emergency"]]
    confs = [r["asr"].confidence for r in rows if r["asr"].confidence is not None]
    return {
        "n": n, "wer": corpus_wer(refs, hyps),
        "cs_exact": mean([callsign_exact(r["item"], r[key]) for r in rows]),
        "cs_snap": mean([callsign_snapped(r["item"], r[key]) for r in rows]),
        "cs_safe": mean([callsign_safe(r["item"], r[key]) for r in rows]),
        "intent": mean([r[key].intent == r["item"]["intent"] for r in rows]),
        "slot_recall": tp / (tp + fn) if tp + fn else None, "slot_exact": mean(exact),
        "emerg_recall": mean([r[key].emergency for r in emerg_truth]), "emerg_n": len(emerg_truth),
        "e2e": mean([not critical_error(r["item"], r[key]) for r in rows]),
        "asr_conf": mean(confs),
    }


METRIC_COLS = ["n", "WER", "callsign exact", "snapped (strict)", "snapped (safe)", "intent", "slot recall",
               "slots all correct", "emergency recall", "end-to-end ok", "mean ASR conf"]


def metric_row(label: str, m: dict) -> list[str]:
    return [label, str(m["n"]), pct(m["wer"]), pct(m["cs_exact"]), pct(m["cs_snap"]), pct(m["cs_safe"]),
            pct(m["intent"]), pct(m["slot_recall"]), pct(m["slot_exact"]),
            f"{pct(m['emerg_recall'])} ({m['emerg_n']})", pct(m["e2e"]), fmt(m["asr_conf"])]


def calibration(conf: list[float], good: list[bool]) -> tuple[list[list[str]], float | None, float, dict]:
    """Sweep 'hand off if conf < t'. Returns table rows, AUROC, best-Youden t, {t: (handoff, recall)}."""
    n = len(conf)
    bad_total = sum(not g for g in good)
    rows, best_t, best_j, stats = [], THRESHOLDS[0], -9.0, {}
    for t in THRESHOLDS:
        flagged = [c < t for c in conf]
        hand = sum(flagged)
        caught = sum(f and not g for f, g in zip(flagged, good))
        recall = caught / bad_total if bad_total else 0.0
        prec = caught / hand if hand else 0.0
        j = recall - hand / n
        if j > best_j:
            best_j, best_t = j, t
        stats[t] = (hand / n, recall)
        rows.append([f"{t:.2f}", pct(hand / n), pct(recall), pct(prec), f"{j:+.3f}"])
    return rows, auroc([c for c, g in zip(conf, good) if g], [c for c, g in zip(conf, good) if not g]), best_t, stats


def reliability(conf: list[float], good: list[bool]) -> list[list[str]]:
    bins = [(0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 0.98), (0.98, 1.01)]
    rows = []
    for lo, hi in bins:
        sel = [g for c, g in zip(conf, good) if lo <= c < hi]
        rows.append([f"{lo:.2f}-{min(hi, 1.0):.2f}", str(len(sel)),
                     pct(1 - mean([float(x) for x in sel]) if sel else None)])
    return rows


# ------------------------------------------------------------------ ATCO2
def alnum_runs(text: str) -> list[str]:
    """Collapsed digit/letter runs with >=1 letter and >=3 chars (proxy for callsign strings)."""
    out = []
    for kind, toks in group_runs(lex(text)):
        if kind == "run" and any(is_letter_token(t) for t in toks):
            s = collapse_mixed(toks).lower()
            if len(s) >= 3:
                out.append(s)
    return out


def run_atco2(backend: str, resamples: int = 2, model: str = GEMINI_ASR_MODEL) -> list[dict]:
    manifest = [json.loads(x) for x in (ROOT / "audio" / "atco2" / "manifest.jsonl").read_text().splitlines()]

    def run(m: dict) -> dict | None:
        try:
            asr = transcribe(ROOT / m["file"], prompt=GENERIC_PROMPT, backend=backend, resamples=resamples, model=model)
        except CacheMiss:
            return None
        return {"m": m, "asr": asr, "ref": normalize_for_wer(m["text"]), "hyp": normalize_for_wer(asr.text),
                "wer": clip_wer(m["text"], asr.text), "ref_runs": alnum_runs(m["text"]),
                "hyp_runs": alnum_runs(asr.text)}

    with ThreadPoolExecutor(16) as ex:
        return [r for r in ex.map(run, manifest) if r is not None]


def atco_summary(atco: list[dict]) -> dict:
    with_cs = [r for r in atco if r["ref_runs"]]
    per = sorted(r["wer"] for r in atco)
    confs = [r["asr"].confidence or 0.0 for r in atco]
    good = [r["wer"] <= 0.25 for r in atco]
    return {
        "n": len(atco), "wer": corpus_wer([r["ref"] for r in atco], [r["hyp"] for r in atco]),
        "median": per[len(per) // 2], "p90": per[int(0.9 * len(per))],
        "n_cs": len(with_cs), "cs_first": mean([r["ref_runs"][0] in r["hyp_runs"] for r in with_cs]),
        "runs_recall": mean([rr in r["hyp_runs"] for r in with_cs for rr in r["ref_runs"]]),
        "conf": mean(confs), "auroc": auroc([c for c, g in zip(confs, good) if g], [c for c, g in zip(confs, good) if not g]),
        "spearman": spearman(confs, [r["wer"] for r in atco]),
    }


# ------------------------------------------------------------------ gates (issue #3)
def run_gates(rows: list[dict]) -> tuple[list[list[str]], dict]:
    bank = load_bank()
    raws = []
    with ThreadPoolExecutor(16) as ex:
        raws = list(ex.map(lambda it: llm_raw(it["text"]), bank))
    valid = mean([r["valid"] for r in raws])
    lat_llm = statistics.median(r["latency_s"] for r in raws)
    p95_llm = sorted(r["latency_s"] for r in raws)[int(0.95 * len(raws)) - 1]
    pipe = statistics.median(r["pipeline_s"] for r in rows)
    called = [r for r in rows if r["llm_called"]]
    reason_ok = mean([bool(r["final"].reason.strip()) for r in rows])
    data_md = (ROOT / "DATA.md").read_text() if (ROOT / "DATA.md").exists() else ""
    no_liveatc = "No LiveATC audio" in data_md
    gates = [
        ["Parser LLM returns valid JSON on the bank (>= 90%)", f"{pct(valid)} ({sum(r['valid'] for r in raws)}/{len(raws)})",
         "PASS" if valid >= 0.9 else "FAIL"],
        ["Median parse latency < 1.5 s (forced LLM call per bank utterance)", f"{lat_llm:.2f} s (p95 {p95_llm:.2f} s)",
         "PASS" if lat_llm < 1.5 else "FAIL"],
        ["Median parse latency < 1.5 s (full pipeline, grammar first, LLM only when unsure)",
         f"{pipe * 1000:.1f} ms over {len(rows)} clips; LLM used on {pct(len(called) / len(rows))}",
         "PASS" if pipe < 1.5 else "FAIL"],
        ["Every ParsedTransmission carries a non-empty `reason`", f"{pct(reason_ok)} of {len(rows)} parses",
         "PASS" if reason_ok == 1.0 else "FAIL"],
        ["DATA.md states that no LiveATC audio is used", "present" if no_liveatc else "missing",
         "PASS" if no_liveatc else "FAIL"],
    ]
    return gates, {"valid": valid, "llm_median_s": lat_llm, "pipeline_median_s": pipe}


# ------------------------------------------------------------------ report
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asr", choices=["gemini", "openai"], default="gemini", help="primary ASR backend")
    args = ap.parse_args()
    ensure_gemini_key()

    manifest = [json.loads(x) for x in (ROOT / "manifest.jsonl").read_text().splitlines()]
    by_prov = {p: [m for m in manifest if m["provider"] == p] for p in ("gemini", "openai")}
    A = run_set(by_prov["gemini"], args.asr)             # Gemini-TTS clips, primary ASR
    B = run_set(by_prov["openai"], "gemini", resamples=0)   # OpenAI-TTS clips, Gemini ASR (one call per clip)
    C = run_set(by_prov["openai"], "openai")             # OpenAI-TTS clips, OpenAI ASR (cache only)
    head = A if A else (C if args.asr == "openai" else B)
    head_name = (f"Gemini TTS clips, {args.asr} ASR" if A else "OpenAI TTS clips")
    atco_g = run_atco2("gemini")
    atco_o = run_atco2("openai")
    atco_head = atco_g if args.asr == "gemini" else atco_o

    out: list[str] = []
    w = out.append
    w("# Landed speech: transcription and parsing results\n")
    w(f"Generated by `uv run python eval.py --asr {args.asr}`. ASR: Gemini `{GEMINI_ASR_MODEL}` (primary) and OpenAI "
      f"`{OPENAI_ASR_MODEL}` (cache only). Parser fallback LLM: Gemini `{LLM_MODEL}` with a response schema. TTS: Gemini "
      f"`gemini-3.8-flash-lite-tts` (Charon, Kore, Fenrir) plus an extra OpenAI voice set `gpt-4o-mini-tts` (onyx, nova, ash).\n")
    w(f"Synthetic sets: Gemini-TTS {len(A)} clips, OpenAI-TTS {len(B)} clips (Gemini ASR) / {len(C)} clips (OpenAI ASR), "
      f"from {len(load_bank())} scripted utterances. ATCO2: {len(atco_g)} real clips.\n")
    w("**Read these numbers with care.** The grammar and the NYC vocabulary prompt were written against the same "
      "script bank the synthetic clips come from, so parsing scores on synthetic clips are an optimistic, "
      "in-distribution bound. The channel is simulated (band-pass, clipping, hiss, rotor bed), not real VHF. Only "
      "the ATCO2 section uses real recordings, and those are European ATC, not NYC helicopter traffic. Neither TTS "
      "provider is guaranteed to say exactly the script (WER includes TTS slips).\n")

    # ---- gates
    gates, gate_vals = run_gates(head)
    w("## 0. Acceptance gates (issue #3)\n")
    w(table(["gate", "measured", "result"], gates))
    w("")

    # ---- headline
    w(f"## 1. Synthetic radio: headline by SNR ({head_name})\n")
    by_snr = {s: [r for r in head if r["m"]["snr"] == s] for s in SNR_ORDER}
    w(table(["SNR (dB)"] + METRIC_COLS, [metric_row(s, synth_metrics(by_snr[s])) for s in SNR_ORDER if by_snr[s]]))
    w("\nDefinitions: WER is corpus-level on normalised text (spoken numbers and phonetic runs collapsed, so "
      "'five hundred' = '500'). *callsign exact*: parsed callsign characters equal the truth. *snapped (strict)*: "
      "`snapped_to` equals the true registration. *snapped (safe)*: correct snap, or an ambiguity flag whose "
      "candidate list contains the truth. *slot recall*: non-null truth slots recovered exactly. *slots all "
      "correct*: all 8 slots match (including nulls). *end-to-end ok*: callsign (safe), intent, emergency flag "
      "and all slots correct.\n")
    w("### By voice\n")
    voices = sorted({r["m"]["voice"] for r in head})
    w(table(["voice"] + METRIC_COLS, [metric_row(v, synth_metrics([r for r in head if r["m"]["voice"] == v])) for v in voices]))
    w("\n### By SNR x voice (end-to-end ok / WER)\n")
    cr = []
    for s in SNR_ORDER:
        line = [s]
        for v in voices:
            sel = [r for r in by_snr[s] if r["m"]["voice"] == v]
            m = synth_metrics(sel) if sel else None
            line.append(f"{pct(m['e2e'])} / {pct(m['wer'])} (n={m['n']})" if m else "-")
        cr.append(line)
    w(table(["SNR"] + voices, cr))
    w("\n### Rotor-noise bed (SNR 10, 5, 0 and -5; rotor applied to odd-numbered scripts)\n")
    rr = []
    for rot in (False, True):
        sel = [r for r in head if r["m"]["snr"] in ("10", "5", "0", "-5") and r["m"]["rotor"] == rot]
        rr.append(metric_row("rotor" if rot else "no rotor", synth_metrics(sel)))
    w(table(["condition"] + METRIC_COLS, rr))
    w("\n### Per-slot recall (all SNRs, final parser)\n")
    sr_rows = []
    for k in SLOT_NAMES:
        hit = tot = wrong = 0
        for r in head:
            t, p = truth_slots(r["item"])[k], pred_slots(r["final"])[k]
            if t is not None:
                tot += 1
                hit += t == p
            elif p is not None:
                wrong += 1
        sr_rows.append([k, str(tot), pct(hit / tot if tot else None), str(wrong)])
    w(table(["slot", "truth count", "recall", "spurious values"], sr_rows))

    w("\n### Grammar-only vs grammar + LLM fallback\n")
    gm, fm = synth_metrics(head, "grammar"), synth_metrics(head, "final")
    w(table(["parser", "callsign exact", "snapped (safe)", "intent", "slot recall", "slots all correct", "end-to-end ok"],
            [[name, pct(m["cs_exact"]), pct(m["cs_safe"]), pct(m["intent"]), pct(m["slot_recall"]), pct(m["slot_exact"]), pct(m["e2e"])]
             for name, m in (("grammar only", gm), ("grammar + LLM", fm))]))
    n_llm = sum(r["final"].parser == "llm" for r in head)
    w(f"\nThe LLM was consulted on {pct(mean([r['llm_called'] for r in head]))} of clips and its result replaced the "
      f"grammar result on {n_llm} of {len(head)} ({pct(n_llm / len(head))}).\n")

    amb = [r for r in head if r["item"]["callsign"].get("ambiguous")]
    nonamb = [r for r in head if r["item"]["callsign"].get("snapped_to") and not r["item"]["callsign"].get("ambiguous")]
    w("### Callsign ambiguity (scenario S4)\n")
    w(table(["set", "n", "ambiguity flagged", "truth within candidates"],
            [["truncated callsigns (true near-ties)", str(len(amb)), pct(mean([bool(r["final"].callsign.ambiguous_with) for r in amb])),
              pct(mean([callsign_safe(r["item"], r["final"]) for r in amb]))],
             ["full callsigns (should not flag)", str(len(nonamb)), pct(mean([bool(r["final"].callsign.ambiguous_with) for r in nonamb])),
              pct(mean([callsign_safe(r["item"], r["final"]) for r in nonamb]))]]))

    # ---- provider comparison
    w("\n## 2. Gemini vs OpenAI transcription, side by side\n")
    w("Same audio (OpenAI-TTS clips, which have cached OpenAI transcripts) and the same parser on both transcripts.\n")
    cmp_rows = []
    for s in SNR_ORDER + ["all"]:
        b = [r for r in B if s == "all" or r["m"]["snr"] == s]
        c = [r for r in C if s == "all" or r["m"]["snr"] == s]
        if not b or not c:
            continue
        mb, mc = synth_metrics(b), synth_metrics(c)
        cmp_rows.append([s, str(mb["n"]), pct(mb["wer"]), pct(mc["wer"]), pct(mb["cs_exact"]), pct(mc["cs_exact"]),
                         pct(mb["e2e"]), pct(mc["e2e"])])
    w(table(["SNR", "n", "WER Gemini", "WER OpenAI", "callsign Gemini", "callsign OpenAI", "e2e Gemini", "e2e OpenAI"], cmp_rows))
    if atco_g and atco_o:
        sg, so = atco_summary(atco_g), atco_summary(atco_o)
        w("\nReal audio (ATCO2, generic ATC prompt for both):\n")
        w(table(["metric", "Gemini", "OpenAI"], [
            ["corpus WER", pct(sg["wer"]), pct(so["wer"])],
            ["median / p90 clip WER", f"{pct(sg['median'])} / {pct(sg['p90'])}", f"{pct(so['median'])} / {pct(so['p90'])}"],
            ["identifier exact match (callsign proxy)", pct(sg["cs_first"]), pct(so["cs_first"])],
            ["identifier recall (all alphanumeric runs)", pct(sg["runs_recall"]), pct(so["runs_recall"])]]))
        wg, wo = sg["wer"], so["wer"]
        e2g = synth_metrics(B)["e2e"] if B else None
        e2o = synth_metrics(C)["e2e"] if C else None
        winner = "Gemini" if (wg is not None and wo is not None and wg < wo) else "OpenAI"
        w(f"\n**Transcription winner on ATCO2 WER: {winner}** (Gemini {pct(wg)}, OpenAI {pct(wo)}). On the OpenAI-TTS "
          f"synthetic clips overall, end-to-end correctness is Gemini {pct(e2g)} vs OpenAI {pct(e2o)}.\n")
    # ---- Gemini model / prompt ablation
    w("### Gemini model and prompt ablation\n")
    w("OpenAI-TTS clips at 5 and 0 dB (96 clips, one call per clip) and the 100 ATCO2 clips (generic prompt). "
      "*wrong callsign* = a callsign was heard but is not the true one (a confident mis-hear, the dangerous case; "
      "a roster-callsign prompt can make the model echo roster names that were never spoken).\n")
    sub = [m for m in by_prov["openai"] if m["snr"] in ("5", "0")]
    abl_rows = []
    for mdl in ("gemini-3.5-flash-lite", "gemini-3.7-flash", "gemini-3.8-flash"):
        atco_m = atco_summary(run_atco2("gemini", 0, mdl))
        for pname, pr in (("vocab + roster callsigns", None), ("vocab only", nyc_prompt(False))):
            rs = run_set(sub, "gemini", 0, mdl, pr)
            sm = synth_metrics(rs)
            wrong = mean([bool(r["final"].callsign.normalized) and not callsign_exact(r["item"], r["final"]) for r in rs])
            abl_rows.append([mdl, pname, pct(sm["wer"]), pct(sm["cs_exact"]), pct(wrong), pct(sm["e2e"]),
                             pct(atco_m["wer"]) if pr is None else "same"])
    oc = [r for r in C if r["m"]["snr"] in ("5", "0")]
    if oc:
        sm = synth_metrics(oc)
        wrong = mean([bool(r["final"].callsign.normalized) and not callsign_exact(r["item"], r["final"]) for r in oc])
        so_ = atco_summary(atco_o) if atco_o else None
        abl_rows.append([f"{OPENAI_ASR_MODEL} (reference)", "vocab + roster callsigns", pct(sm["wer"]), pct(sm["cs_exact"]),
                         pct(wrong), pct(sm["e2e"]), pct(so_["wer"]) if so_ else "n/a"])
    w(table(["model", "prompt", "synth WER (5+0 dB)", "callsign exact", "wrong callsign", "end-to-end ok", "ATCO2 WER"], abl_rows))
    w("")
    w("### Voice sets under the same ASR (Gemini ASR)\n")
    vs = [metric_row("Gemini TTS", synth_metrics(A)) if A else None, metric_row("OpenAI TTS", synth_metrics(B)) if B else None]
    w(table(["voice set"] + METRIC_COLS, [v for v in vs if v]))

    # ---- calibration
    w("\n## 3. Does `asr_confidence` predict errors?\n")
    conf = [r["asr"].confidence or 0.0 for r in head]
    good = [not critical_error(r["item"], r["final"]) for r in head]
    wer_good = [clip_wer(r["m"]["ground_truth"]["text"], r["asr"].text) <= 0.10 for r in head]
    cal_rows, auc, best_t, stats_synth = calibration(conf, good)
    cal_rows_w, auc_w, best_t_w, _ = calibration(conf, wer_good)
    sp = spearman(conf, [clip_wer(r["m"]["ground_truth"]["text"], r["asr"].text) for r in head])
    if args.asr == "gemini":
        w("Gemini 3.x exposes no token logprobs, so `asr_confidence` is built from `audio_quality x (1 - uncertain "
          "word share)` as self-reported by the model (`conf_self`) times agreement between the transcript and two "
          "temperature-1 resamples (`conf_consistency`). Signal comparison:\n")
        sig_rows = []
        for name, getter in (("conf_self", lambda r: r["asr"].conf_self), ("conf_consistency", lambda r: r["asr"].conf_consistency),
                             ("product (asr_confidence)", lambda r: r["asr"].confidence)):
            xs = [getter(r) or 0.0 for r in head]
            sig_rows.append([name, fmt(auroc([x for x, g in zip(xs, good) if g], [x for x, g in zip(xs, good) if not g])),
                             fmt(auroc([x for x, g in zip(xs, wer_good) if g], [x for x, g in zip(xs, wer_good) if not g])),
                             fmt(spearman(xs, [clip_wer(r["m"]["ground_truth"]["text"], r["asr"].text) for r in head]))])
        w(table(["signal", "AUROC (end-to-end correct)", "AUROC (WER<=10%)", "Spearman vs WER"], sig_rows))
        if C:
            cc = [r["asr"].confidence or 0.0 for r in C]
            cg = [not critical_error(r["item"], r["final"]) for r in C]
            w(f"\nFor reference, OpenAI's logprob confidence on its clips: AUROC {fmt(auroc([c for c, g in zip(cc, cg) if g], [c for c, g in zip(cc, cg) if not g]))} "
              f"(end-to-end), Spearman vs WER {fmt(spearman(cc, [clip_wer(r['m']['ground_truth']['text'], r['asr'].text) for r in C]))}.\n")
    w(f"\nHeadline set (n={len(head)}): critical-error rate {pct(1 - mean([float(g) for g in good]))}, AUROC (end-to-end) "
      f"{fmt(auc)}, AUROC (WER<=10%) {fmt(auc_w)}, Spearman(conf, WER) {fmt(sp)}.\n")
    w("Reliability (error = any critical end-to-end error):\n")
    w(table(["confidence bin", "n", "error rate"], reliability(conf, good)))
    w("\nThreshold sweep, rule 'hand off if asr_confidence < t' (error = critical end-to-end error):\n")
    w(table(["t", "handoff rate", "error recall", "precision", "Youden J"], cal_rows))
    w("\nSame sweep, error = transcript WER > 10%:\n")
    w(table(["t", "handoff rate", "error recall", "precision", "Youden J"], cal_rows_w))
    at06 = next(r for r in cal_rows if r[0] == "0.60")
    w(f"\nThe spec's 0.6 threshold hands off {at06[1]} of synthetic clips and catches {at06[2]} of critical errors.\n")

    a_conf = [r["asr"].confidence or 0.0 for r in atco_head]
    a_good = [r["wer"] <= 0.25 for r in atco_head]
    a_cal, a_auc, a_best, stats_atco = calibration(a_conf, a_good)
    sa = atco_summary(atco_head)

    # ---- ATCO2
    w(f"## 4. Real audio: ATCO2 test subset (European ATC), {args.asr} ASR\n")
    w(table(["metric", "value"], [
        ["clips / minutes", f"{sa['n']} / {sum(r['m']['duration'] for r in atco_head) / 60:.1f}"],
        ["corpus WER (normalised)", pct(sa["wer"])],
        ["median / p90 per-clip WER", f"{pct(sa['median'])} / {pct(sa['p90'])}"],
        ["clips with a letter+digit identifier in the reference", str(sa["n_cs"])],
        ["identifier exact match (first alphanumeric run, callsign proxy)", pct(sa["cs_first"])],
        ["identifier recall (all alphanumeric runs)", pct(sa["runs_recall"])],
        ["mean ASR confidence", fmt(sa["conf"])],
        ["AUROC of confidence for 'clip WER <= 25%'", fmt(sa["auroc"])],
        ["Spearman(conf, WER)", fmt(sa["spearman"])],
    ]))
    w("\n**Caveats.** ATCO2 is European ATC (Swiss and Czech airports; airline telephony callsigns such as 'csa one "
      "delta zulu', metric and ICAO runway phraseology, non-native English, often poor audio). NYC helicopter calls use "
      "tail numbers and VFR phraseology, so treat this as a stress test of ASR on genuine radio noise rather than "
      "an estimate of Landed's NYC accuracy. The model is called with a generic ATC prompt (no NYC vocabulary). "
      "'Callsign' here is a proxy: the first run of phonetic letters and digits (>=3 characters, at least one "
      "letter) in the reference transcript, which the HF release does not annotate.\n")
    w("Threshold sweep on ATCO2 (error = clip WER > 25%):\n")
    w(table(["t", "handoff rate", "error recall", "precision", "Youden J"], a_cal))
    w("")

    # ---- recommendation
    ok = [t for t in THRESHOLDS if stats_synth[t][1] >= RECALL_TARGET and stats_atco[t][1] >= RECALL_TARGET]
    rec = ok[0] if ok else None
    w("## 5. Suggested ASR-confidence threshold\n")
    w(f"* Headline synthetic set, best Youden-J threshold **{best_t:.2f}** (AUROC {fmt(auc)}); WER>10% target: **{best_t_w:.2f}**.")
    w(f"* ATCO2 (real audio, WER>25% target): best Youden-J threshold **{a_best:.2f}** (AUROC {fmt(a_auc)}).")
    if rec is not None:
        w(f"* Rule used: the lowest t that catches at least {int(RECALL_TARGET * 100)}% of errors on both sets. "
          f"**Suggested threshold: {rec:.2f}**. It hands off {pct(stats_synth[rec][0])} of synthetic clips "
          f"(catching {pct(stats_synth[rec][1])} of critical errors) and {pct(stats_atco[rec][0])} of ATCO2 clips "
          f"(catching {pct(stats_atco[rec][1])} of bad transcripts).")
    else:
        w(f"* No single threshold catches {int(RECALL_TARGET * 100)}% of errors on both sets; use the per-set tables above.")
    w("")

    # ---- worst failures
    w("## 6. Worst failure cases (headline synthetic set)\n")
    bad = [r for r in head if critical_error(r["item"], r["final"])]
    bad.sort(key=lambda r: (-(len(slot_diffs(r["item"], r["final"])) + (not callsign_safe(r["item"], r["final"])) + (r["final"].intent != r["item"]["intent"])), r["asr"].confidence or 0))
    fr = []
    for r in bad[:20]:
        pt = r["final"]
        what = []
        if not callsign_safe(r["item"], pt):
            what.append(f"callsign {r['item']['callsign'].get('snapped_to')} -> {pt.callsign.normalized}/{pt.callsign.snapped_to}")
        if pt.intent != r["item"]["intent"]:
            what.append(f"intent {r['item']['intent']} -> {pt.intent}")
        if pt.emergency != r["item"]["emergency"]:
            what.append("emergency flag wrong")
        for k, (t, p) in slot_diffs(r["item"], pt).items():
            what.append(f"{k}: {t} -> {p}")
        fr.append([r["m"]["utterance_id"], f"{r['m']['voice']}/{r['m']['snr']}", fmt(r["asr"].confidence, 2), pt.parser,
                   "; ".join(what), r["asr"].text.replace("|", "/")])
    w(f"{len(bad)} of {len(head)} clips have at least one critical error. Worst 20:\n")
    w(table(["utterance", "voice/SNR", "ASR conf", "parser", "errors (truth -> got)", "ASR text"], fr))
    w("\n### Worst ATCO2 clips (highest WER)\n")
    worst = sorted(atco_head, key=lambda r: -r["wer"])[:8]
    w(table(["id", "WER", "conf", "reference", "hypothesis"],
            [[r["m"]["id"][-40:], pct(r["wer"]), fmt(r["asr"].confidence, 2), r["ref"], r["hyp"]] for r in worst]))

    (ROOT / "RESULTS.md").write_text("\n".join(out) + "\n")
    (ROOT / ".cache").mkdir(exist_ok=True)
    (ROOT / ".cache" / "last_eval.json").write_text(json.dumps({
        "suggested_threshold": rec, "best_t_synth": best_t, "best_t_atco2": a_best, "gates": gate_vals,
        "synth_auroc": auc, "atco2_auroc": a_auc}))
    print("wrote RESULTS.md; gates:", [g[2] for g in gates])


if __name__ == "__main__":
    main()
