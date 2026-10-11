"""Publish only aggregate/model-proposed review evidence, never audited gold."""

import argparse
import json
from collections import Counter
from pathlib import Path

from assisted_audit import AudioReview, protocol
from experiment import RESERVATION, digest, dump, load_frozen, normalize_for_wer


def report(source, directory, output):
    plan, manifest, baseline = load_frozen(source)
    expected = protocol(source)
    sealed = json.loads((directory / "protocol.json").read_text())
    if sealed != expected:
        raise ValueError("Changed audit protocol or parent inputs")
    protocol_hash = digest((directory / "protocol.json").read_bytes())
    inputs = {row["id"]: row for row in manifest}
    results = [json.loads(path.read_text()) for path in sorted(directory.glob("clip-*.json"))]
    if len(results) != 25 or [r["id"] for r in results] != plan["audit_development"]:
        raise ValueError("Incomplete, duplicate, or reordered audit outputs")
    ledger = json.loads((directory / "budget.json").read_text())["reservations"]
    if len(ledger) != 25 or len({r["key"] for r in ledger}) != 25:
        raise ValueError("Expected exactly 25 unique reserved attempts")
    languages, fields, cases = Counter(), Counter(), []
    for row in results:
        key = row["id"]
        if row["protocol_sha256"] != protocol_hash or row["pcm_sha256"] != inputs[key]["pcm_sha256"]:
            raise ValueError("Result protocol/PCM changed")
        review = AudioReview.model_validate(row["review"]) if not row["error"] else None
        proposed = []
        if review:
            languages.update(set(review.languages))
            fields.update(field.kind for field in review.fields)
            for field in review.fields:
                proposed.append(
                    {
                        "kind": field.kind,
                        "value": field.value,
                        "alternatives": field.alternatives,
                        "model_certainty_unvalidated": field.certainty,
                        "approximate_span_s_unvalidated": [field.start_s, field.end_s],
                    }
                )
        normalized = normalize_for_wer(review.transcript) if review else None
        cases.append(
            {
                "id": key,
                "human_validated": False,
                "error": row["error"],
                "model_languages_unvalidated": review.languages if review else [],
                "matches_frozen_reference_after_normalization": normalized == baseline[key]["reference"]
                if review
                else None,
                "matches_cached_baseline_after_normalization": normalized == baseline[key]["hypothesis"]
                if review
                else None,
                "model_cautions_count": len(review.cautions) if review else None,
                "model_proposed_fields_not_gold": proposed,
                "private_result_sha256": digest((directory / f"clip-{len(cases):02d}.json").read_bytes()),
            }
        )
    parent_files = sorted((source / "cache").glob("*.json"))
    parent_cache = [json.loads(path.read_text()) for path in parent_files]
    parent_known = sum(row.get("estimated_usd") or 0 for row in parent_cache)
    parent_unknown = sum(row.get("estimated_usd") is None for row in parent_cache)
    parent_cache_hash = digest(
        json.dumps({path.name: digest(path.read_bytes()) for path in parent_files}, sort_keys=True).encode()
    )
    known = sum(row.get("estimated_usd") or 0 for row in results)
    reserved = len(ledger) * RESERVATION
    dump(
        output,
        {
            "status": "Reference-blind Gemini-assisted audit; not human adjudication or validated gold",
            "protocol_sha256": protocol_hash,
            "attempted": 25,
            "structured_reviews": sum(not r["error"] for r in results),
            "failed_attempts": sum(bool(r["error"]) for r in results),
            "human_adjudicated": 0,
            "gold_changes": 0,
            "languages_model_proposed_clip_counts": dict(languages),
            "field_type_model_proposed_counts": dict(fields),
            "normalized_exact_reference_matches": sum(
                c["matches_frozen_reference_after_normalization"] is True for c in cases
            ),
            "model_uncertain_field_count": sum(
                f["model_certainty_unvalidated"] == "uncertain"
                for c in cases
                for f in c["model_proposed_fields_not_gold"]
            ),
            "cost": {
                "audit_known_usage_estimated_usd": known,
                "audit_unknown_usage_attempts": sum(r.get("estimated_usd") is None for r in results),
                "audit_conservative_reserved_usd": reserved,
                "parent_known_success_estimated_usd": parent_known,
                "parent_unknown_usage_attempts": parent_unknown,
                "parent_response_cache_sha256": parent_cache_hash,
                "combined_known_usage_estimated_usd": known + parent_known,
                "combined_conservative_reserved_usd": expected["previous_reserved_usd"] + reserved,
                "note": "Estimates, not receipts. Unknown-usage failures retain full reservations.",
            },
            "limitations": [
                "Same Gemini family as evaluated ASR; reference blindness does not make it an independent human judge.",
                "Model language labels, field certainty, alternatives, and timestamps are unverified.",
                "Schema speed field conflates possible wind/aircraft speed; no operational field accuracy calculated.",
                "Normalized matches do not validate acoustic correctness; nonmatches do not prove bad references.",
                "Noncommercial, error-enriched development sample; no fresh holdout or model-selection evidence.",
            ],
            "cases": cases,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report(args.source, args.directory, args.output)
