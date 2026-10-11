"""Private, reproducible UWB research evaluation; never publish audio or transcripts.

Run with the locked speech environment. Preparation never calls a provider.
"""

import argparse
import hashlib
import io
import json
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import jiwer
import numpy as np
import pandas as pd
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "speech"))
from asr import GEMINI_ASR_MODEL, GENERIC_PROMPT, transcribe  # noqa: E402
from normalize import normalize_for_wer  # noqa: E402

REVISION = "1e8270beb8c1643c8735dddb7229fffb0e399f74"
PARQUET_SHA = "6a637e5b035c4e22bdf880554c900c3a775eac46c10dc9713e827dd6cbf38783"
SEED = 34


def pcm_hash(audio, rate):
    """Exact decoded mono/sample equality only; not a perceptual overlap detector."""
    values = np.asarray(audio, dtype="<f4")
    return hashlib.sha256(
        str((rate, values.shape)).encode() + values.tobytes()
    ).hexdigest()


def read_audio(data):
    values, rate = sf.read(io.BytesIO(data), dtype="float32")
    return values, rate, pcm_hash(values, rate)


def prepare(directory, baseline):
    parquet = directory / "uwb-test.parquet"
    if hashlib.sha256(parquet.read_bytes()).hexdigest() != PARQUET_SHA:
        raise RuntimeError("UWB parquet does not match pinned release SHA256")
    baseline_rows = [json.loads(line) for line in baseline.read_text().splitlines()]
    if len(baseline_rows) != 100:
        raise RuntimeError("Expected the existing 100-clip ATCO2 evaluation manifest")
    baseline_hashes = set()
    baseline_texts = set()
    for row in baseline_rows:
        values, rate = sf.read(baseline.parents[2] / row["file"], dtype="float32")
        baseline_hashes.add(pcm_hash(values, rate))
        baseline_texts.add(normalize_for_wer(row["text"]))
    groups = defaultdict(list)
    seen = set()
    counts = Counter(exact_atco2_audio_matches_full_test=0, duplicate_audio_full_test=0)
    source = pd.read_parquet(parquet)
    for _, row in source.iterrows():
        match = re.fullmatch(r"(uwb-atcc_.+)_\d+_\d+_([A-Z]+)", row["id"])
        if not match:
            raise RuntimeError(f"Unrecognized source lineage: {row['id']}")
        values, rate, digest = read_audio(row["audio"]["bytes"])
        counts["exact_atco2_audio_matches_full_test"] += digest in baseline_hashes
        if digest in seen:
            counts["duplicate_audio_full_test"] += 1
            continue
        seen.add(digest)
        duration = len(values) / rate
        if not 2 <= duration <= 20 or len(row["text"].split()) < 4:
            continue
        if digest in baseline_hashes:
            continue
        groups[match[1]].append(
            {
                "id": row["id"],
                "session": match[1],
                "role": match[2],
                "start_s": float(row["segment_start_time"]),
                "end_s": float(row["segment_end_time"]),
                "duration_s": duration,
                "sample_rate": rate,
                "pcm_sha256": digest,
                "text": row["text"],
                "data": row["audio"]["bytes"],
            }
        )
    rng = random.Random(SEED)
    sessions = sorted(groups)
    rng.shuffle(sessions)
    for group in groups.values():
        # Stable source order followed by a seeded shuffle.
        group.sort(key=lambda row: row["id"])
        rng.shuffle(group)
    selected = []
    while len(selected) < 150:
        progressed = False
        for session in sessions:
            if groups[session] and len(selected) < 150:
                selected.append(groups[session].pop())
                progressed = True
        if not progressed:
            raise RuntimeError("Fewer than 150 eligible unique UWB clips")
    clips = directory / "clips"
    clips.mkdir(exist_ok=True)
    for row in selected:
        data = row.pop("data")
        values, rate, _ = read_audio(data)
        path = clips / (row["id"] + ".wav")
        sf.write(path, values, rate, subtype="PCM_16")
        # Detect any change caused by WAV conversion before using the reference hash.
        decoded, actual_rate = sf.read(path, dtype="float32")
        if pcm_hash(decoded, actual_rate) != row["pcm_sha256"]:
            raise RuntimeError("WAV conversion changed PCM samples")
        row["file"] = str(path)
    manifest = directory / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in selected))
    durations = [row["duration_s"] for row in selected]
    summary = {
        "source": "Jzuluaga/uwb_atcc",
        "revision": REVISION,
        "parquet_sha256": PARQUET_SHA,
        "seed": SEED,
        "sampling": "seeded round-robin over recording sessions; unique decoded PCM; 2–20s and >=4 words",
        "source_test_rows": len(source),
        "eligible_sessions": len(sessions),
        "n": len(selected),
        "sessions": dict(sorted(Counter(row["session"] for row in selected).items())),
        "roles": dict(Counter(row["role"] for row in selected)),
        "duration_minutes": sum(durations) / 60,
        "duration_median_s": statistics.median(durations),
        "duration_min_s": min(durations),
        "duration_max_s": max(durations),
        "baseline_atco2_clips": len(baseline_rows),
        **counts,
        "selected_exact_atco2_audio_matches": sum(
            row["pcm_sha256"] in baseline_hashes for row in selected
        ),
        "selected_normalized_transcript_matches": sum(
            normalize_for_wer(row["text"]) in baseline_texts for row in selected
        ),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "selected_audio_hashes": [row["pcm_sha256"] for row in selected],
    }
    (directory / "sample-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "selected_audio_hashes"}, indent=2
        )
    )


def frozen_manifest(directory):
    manifest = directory / "manifest.jsonl"
    sample = json.loads((directory / "sample-summary.json").read_text())
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if digest != sample["manifest_sha256"] or sample["revision"] != REVISION:
        raise RuntimeError("Frozen manifest or source revision changed")
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    if len(rows) != 150 or len({row["pcm_sha256"] for row in rows}) != 150:
        raise RuntimeError("Expected exactly 150 distinct prepared recordings")
    return rows, digest


def verify_results(directory):
    rows, digest = frozen_manifest(directory)
    results_path = directory / "private-results.jsonl"
    results = [json.loads(line) for line in results_path.read_text().splitlines()]
    expected = {row["id"]: row for row in rows}
    if len(results) != 150 or {r["id"] for r in results} != set(expected):
        raise RuntimeError("Results do not cover the complete frozen sample")
    for result in results:
        row = expected[result["id"]]
        if (
            result["reference"] != normalize_for_wer(row["text"])
            or result["session"] != row["session"]
            or result["role"] != row["role"]
            or result["hypothesis"] != normalize_for_wer(result["asr"]["text"])
        ):
            raise RuntimeError("Result lineage or transcript normalization changed")
    summary_path = directory / "evaluation-summary.json"
    summary = json.loads(summary_path.read_text())
    measured = jiwer.wer(
        [r["reference"] for r in results], [r["hypothesis"] for r in results]
    )
    if summary["n"] != 150 or abs(summary["corpus_wer"] - measured) > 1e-12:
        raise RuntimeError("Summary does not match complete private results")
    summary.update(
        manifest_sha256=digest,
        source_revision=REVISION,
        private_results_sha256=hashlib.sha256(results_path.read_bytes()).hexdigest(),
    )
    temporary = summary_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(summary, indent=2) + "\n")
    temporary.replace(summary_path)
    print("Verified 150 complete results against frozen manifest and summary WER")


def evaluate(directory, workers):
    rows, _ = frozen_manifest(directory)
    # A failed or interrupted rerun must not leave an old success summary.
    (directory / "evaluation-summary.json").unlink(missing_ok=True)
    from keys import ensure_gemini_key

    ensure_gemini_key()  # Load existing personal key once; never print it.
    output = directory / "private-results.jsonl"
    completed = []
    started = time.monotonic()

    def run(row):
        actual, rate = sf.read(row["file"], dtype="float32")
        if pcm_hash(actual, rate) != row["pcm_sha256"]:
            raise RuntimeError("Prepared audio changed after freezing the sample")
        result = transcribe(
            row["file"],
            prompt=GENERIC_PROMPT,
            backend="gemini",
            resamples=0,
            model=GEMINI_ASR_MODEL,
        )
        ref, hyp = normalize_for_wer(row["text"]), normalize_for_wer(result.text)
        return {
            "id": row["id"],
            "session": row["session"],
            "role": row["role"],
            "reference": ref,
            "hypothesis": hyp,
            "wer": jiwer.wer(ref, hyp),
            "asr": result.to_dict(),
        }

    with output.open("w") as handle, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, row) for row in rows]
        for future in as_completed(futures):
            result = (
                future.result()
            )  # Fail on provider errors; never silently drop a clip.
            completed.append(result)
            handle.write(json.dumps(result) + "\n")
            handle.flush()
            if len(completed) % 10 == 0:
                print(f"Completed {len(completed)}/150", flush=True)
    completed.sort(key=lambda row: row["id"])
    refs = [row["reference"] for row in completed]
    hyps = [row["hypothesis"] for row in completed]

    def score(subset):
        return jiwer.wer(
            [r["reference"] for r in subset], [r["hypothesis"] for r in subset]
        )

    latencies = [
        r["asr"]["latency_s"]
        for r in completed
        if not r["asr"]["cached"] and r["asr"]["latency_s"] is not None
    ]
    stats = jiwer.process_words(refs, hyps)
    summary = {
        "n": len(completed),
        "model": GEMINI_ASR_MODEL,
        "prompt": GENERIC_PROMPT,
        "resamples": 0,
        "workers": workers,
        "corpus_wer": stats.wer,
        "word_counts": {
            "substitutions": stats.substitutions,
            "deletions": stats.deletions,
            "insertions": stats.insertions,
            "reference_words": stats.hits + stats.substitutions + stats.deletions,
        },
        "clip_wer_median": statistics.median(r["wer"] for r in completed),
        "exact_transcript_clips": sum(
            r["reference"] == r["hypothesis"] for r in completed
        ),
        "empty_hypotheses": sum(not r["hypothesis"] for r in completed),
        "cached_clips": sum(r["asr"]["cached"] for r in completed),
        "uncached_latency_n": len(latencies),
        "uncached_latency_median_s": statistics.median(latencies)
        if latencies
        else None,
        "uncached_latency_p95_s": sorted(latencies)[
            max(0, int(np.ceil(0.95 * len(latencies))) - 1)
        ]
        if latencies
        else None,
        "wall_s": time.monotonic() - started,
        "role_wer": {
            role: score([r for r in completed if r["role"] == role])
            for role in sorted({r["role"] for r in completed})
        },
        "session_wer": {
            session: score([r for r in completed if r["session"] == session])
            for session in sorted({r["session"] for r in completed})
        },
        "field_accuracy": "Not measured: no manually verified callsign/altitude/intent/emergency labels",
        "handoff_calibration": "Not measured: resamples=0 omits consistency and is not the deployed confidence score",
        "training_overlap": "Unknown Gemini pretraining; source recording train/test disjointness not asserted",
    }
    (directory / "evaluation-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    verify_results(directory)
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "evaluate", "verify"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path)
    parser.add_argument("--paid-gemini-confirmed", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.stage == "prepare":
        if not args.baseline_manifest:
            parser.error("Preparation requires the existing ATCO2 baseline manifest")
        prepare(args.directory, args.baseline_manifest)
    elif args.stage == "verify":
        verify_results(args.directory)
    else:
        if not args.paid_gemini_confirmed:
            parser.error(
                "UWB research evaluation requires confirmed paid Gemini processing"
            )
        if not 1 <= args.workers <= 8:
            parser.error("Use 1–8 workers")
        evaluate(args.directory, args.workers)


if __name__ == "__main__":
    main()
