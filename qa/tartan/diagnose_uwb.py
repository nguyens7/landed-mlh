"""Recompute aggregate diagnostics from private UWB results; no model calls."""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import jiwer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "speech"))
from normalize import normalize_for_wer


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(rows):
    result = jiwer.process_words(
        [r["reference"] for r in rows], [r["hypothesis"] for r in rows]
    )
    return {
        "clips": len(rows),
        "reference_tokens": result.hits + result.substitutions + result.deletions,
        "substitutions": result.substitutions,
        "deletions": result.deletions,
        "insertions": result.insertions,
        "wer": result.wer,
    }


def aliases(text):
    for source, target in {
        "takeoff": "take off",
        "startup": "start up",
        "goodbye": "good bye",
        "lineup": "line up",
    }.items():
        text = re.sub(r"\b" + source + r"\b", target, text)
    return text


def diagnose(results, manifest):
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    selected = [json.loads(line) for line in manifest.read_text().splitlines()]
    ids = [r["id"] for r in rows]
    if (
        len(rows) != 150
        or len(selected) != 150
        or len(set(ids)) != 150
        or set(ids) != {r["id"] for r in selected}
    ):
        raise ValueError("Expected the frozen 150-clip UWB evaluation")
    by_id = {r["id"]: r for r in selected}
    rows.sort(key=lambda r: r["id"])
    if any(r["reference"] != normalize_for_wer(by_id[r["id"]]["text"]) for r in rows):
        raise ValueError("Result reference disagrees with frozen manifest")
    if any(
        not isinstance(r["reference"], str) or not r["reference"].strip() for r in rows
    ):
        raise ValueError("Missing normalized reference")
    # The result references are already normalized by the original evaluator.
    substitutions = Counter()
    for row in rows:
        result = jiwer.process_words(row["reference"], row["hypothesis"])
        if abs(result.wer - row["wer"]) > 1e-9:
            raise ValueError("Cached clip score disagrees with its text")
        for chunk in result.alignments[0]:
            if chunk.type == "substitute":
                ref = result.references[0][chunk.ref_start_idx : chunk.ref_end_idx]
                hyp = result.hypotheses[0][chunk.hyp_start_idx : chunk.hyp_end_idx]
                # Only single-token substitutions; never publish full utterances.
                if len(ref) == len(hyp) == 1:
                    substitutions[(ref[0], hyp[0])] += 1
    confident = [r for r in rows if r["asr"]["conf_self"] >= 0.8]
    return {
        "results_sha256": digest(results),
        "manifest_sha256": digest(manifest),
        "baseline": score(rows),
        "at_least_four_normalized_reference_tokens": score(
            [r for r in rows if len(r["reference"].split()) >= 4]
        ),
        "one_to_three_normalized_reference_tokens": score(
            [r for r in rows if len(r["reference"].split()) < 4]
        ),
        "posthoc_orthography_only": score(
            [
                {
                    **r,
                    "reference": aliases(r["reference"]),
                    "hypothesis": aliases(r["hypothesis"]),
                }
                for r in rows
            ]
        ),
        "orthography_caveat": "Post-hoc diagnostic, not ASR improvement or replacement for headline WER.",
        "self_score_at_least_0_8": {
            "clips": len(confident),
            "clips_with_wer_above_0_25": sum(r["wer"] > 0.25 for r in confident),
        },
        "confidence_caveat": "Single-call self-score; this is not the deployed resampling confidence or field-error calibration.",
        "top_single_token_substitutions": [
            {"reference": ref, "hypothesis": hyp, "count": count}
            for (ref, hyp), count in substitutions.most_common(12)
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(diagnose(args.results, args.manifest), indent=2) + "\n"
    )
