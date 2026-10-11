"""Cost-bounded ASR experiments. Private audio/transcripts never belong in Git."""

import argparse
import fcntl
import hashlib
import importlib.metadata
import io
import json
import math
import platform
import random
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jiwer
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "speech"))
from asr import ASR_INSTRUCTIONS, GENERIC_PROMPT  # noqa: E402
from normalize import normalize_for_wer  # noqa: E402

MODEL = "gemini-3.8-flash"
INPUT_RATE, OUTPUT_RATE = 0.75 / 1e6, 3.75 / 1e6
MAX_INPUT, MAX_OUTPUT = 4096, 8192
RESERVATION = MAX_INPUT * INPUT_RATE + MAX_OUTPUT * OUTPUT_RATE
LITERAL = (
    "Write only the words audibly spoken in this aviation radio clip, in their original order. "
    "Preserve repetitions, false starts, partial phrases, and grammatical errors. "
    "Do not turn a partial call into a standard clearance or infer missing words from aviation conventions. "
    "Keep each audible callsign letter and number; do not replace it with a familiar airline or aircraft name. "
    "Represent clearly spoken numeric sequences with digits, preserving their order and leading zeros. "
    "Never infer a heading, altitude, runway, or callsign from context. "
    "For unclear words give your best hearing in transcript and list those words in uncertain_words. "
    "If no intelligible speech is audible return an empty transcript. "
    "audio_quality rates intelligibility from 0 to 1."
)

DOMAIN = (
    "Air traffic control radio at Prague Ruzyne. Optional regional vocabulary: Ruzyne, Praha, "
    "CSA (an airline designator, not Cessna), Easy, Lufthansa, Austrian, Shamrock, Skytravel, Opera Jet. "
    "These are pronunciation hints only, never required answers. Do not force a callsign to match a hint. "
    "Preserve audible numbers, repetitions and incomplete phrases. Do not translate Czech speech. "
)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def dump(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def numeric(text):
    """Sequence proxy only; not a manually labeled operational field metric."""
    return re.findall(r"\b\d+\b", text)


def boundaries(values, rate):
    """Conservative outer trim; retains internal pauses and 250 ms boundary padding."""
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("Expected finite mono PCM")
    width = max(1, rate // 100)
    rms = np.array([np.sqrt(np.mean(values[i : i + width] ** 2)) for i in range(0, len(values), width)])
    floor = float(np.percentile(rms, 20))
    threshold = max(0.002, floor * 3)
    active = np.flatnonzero(rms > threshold)
    if not len(active):
        return 0, len(values)  # Ambiguous/silent inputs pass through, never invent speech boundaries.
    pad = int(rate * 0.25)
    start, end = (
        max(0, int(active[0]) * width - pad),
        min(len(values), (int(active[-1]) + 1) * width + pad),
    )
    if (end - start) / rate < 0.5:
        return 0, len(values)
    return start, end


def freeze(directory):
    """Seal all experiment inputs, including original per-clip PCM lineage."""
    if (directory / "freeze.json").exists():
        raise ValueError("Experiment already sealed")
    names = ("plan.json", "manifest.json", "baseline.json")
    dump(
        directory / "freeze.json",
        {name: digest((directory / name).read_bytes()) for name in names},
    )
    return load_frozen(directory)


def load_frozen(directory):
    sealed = json.loads((directory / "freeze.json").read_text())
    for name in ("plan.json", "manifest.json", "baseline.json"):
        if digest((directory / name).read_bytes()) != sealed[name]:
            raise ValueError("Frozen experiment input changed: " + name)
    plan = json.loads((directory / "plan.json").read_text())
    rows = json.loads((directory / "manifest.json").read_text())
    baseline = json.loads((directory / "baseline.json").read_text())
    ids = [row["id"] for row in rows]
    partition = plan["audit_development"] + plan["confirmation"] + plan["reserve"]
    if len(ids) != 150 or len(set(ids)) != 150 or sorted(partition) != sorted(ids) or set(baseline) != set(ids):
        raise ValueError("Frozen partition is not complete and disjoint")
    for row in rows:
        if normalize_for_wer(row["text"]) != baseline[row["id"]]["reference"]:
            raise ValueError("Frozen reference mismatch")
        values, rate = sf.read(row["file"], dtype="float32")
        pcm = np.asarray(values, dtype="<f4")
        actual = digest(str((rate, pcm.shape)).encode() + pcm.tobytes())
        if actual != row["pcm_sha256"]:
            raise ValueError("Frozen PCM changed: " + row["id"])
    return plan, rows, baseline


def prepare(directory, source):
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Use a new empty experiment directory; never overwrite a frozen run")
    directory.mkdir(parents=True, exist_ok=True)
    manifest = read_jsonl(source / "manifest.jsonl")
    baseline = {r["id"]: r for r in read_jsonl(source / "private-results.jsonl")}
    if len(manifest) != 150 or len(baseline) != 150 or {r["id"] for r in manifest} != set(baseline):
        raise ValueError("Expected frozen 150-clip evaluation")
    for row in manifest:
        if baseline[row["id"]]["reference"] != normalize_for_wer(row["text"]):
            raise ValueError("Reference mismatch")
    # Audit/error-enriched development cases; confirmation chosen before any new model runs.
    groups = [
        sorted(manifest, key=lambda r: baseline[r["id"]]["wer"], reverse=True),
        sorted(
            manifest,
            key=lambda r: (
                numeric(baseline[r["id"]]["reference"]) != numeric(baseline[r["id"]]["hypothesis"]),
                baseline[r["id"]]["wer"],
            ),
            reverse=True,
        ),
        sorted(manifest, key=lambda r: baseline[r["id"]]["wer"]),
    ]
    rng = random.Random(41)
    shuffled = sorted(manifest, key=lambda r: r["id"])
    rng.shuffle(shuffled)
    groups += [shuffled]
    audit = []
    for group, count in zip(groups, [7, 6, 6, 6], strict=True):
        for row in group:
            if row["id"] not in audit:
                audit.append(row["id"])
                count -= 1
                if count == 0:
                    break
    remaining = [r["id"] for r in shuffled if r["id"] not in audit]
    confirmation = remaining[:75]
    reserve = remaining[75:]
    private_audit = []
    for row in manifest:
        if row["id"] not in audit:
            continue
        audio, rate = sf.read(row["file"], dtype="float32")
        start, end = boundaries(audio, rate)
        base = baseline[row["id"]]
        private_audit.append(
            {
                "id": row["id"],
                "role": row["role"],
                "reference": base["reference"],
                "hypothesis": base["hypothesis"],
                "wer": base["wer"],
                "duration_s": len(audio) / rate,
                "peak": float(np.max(np.abs(audio))),
                "clipped_fraction": float(np.mean(np.abs(audio) >= 0.999)),
                "outer_trim_s": (len(audio) - end + start) / rate,
                "numeric_reference": numeric(base["reference"]),
                "numeric_hypothesis": numeric(base["hypothesis"]),
                "status": "signal/text audit; gold unaltered; not listening-adjudicated",
            }
        )
    plan = {
        "seed": 41,
        "audit_development": audit,
        "confirmation": confirmation,
        "reserve": reserve,
        "source_manifest_sha256": digest((source / "manifest.jsonl").read_bytes()),
        "source_results_sha256": digest((source / "private-results.jsonl").read_bytes()),
        "model": MODEL,
        "literal_prompt_sha256": digest(LITERAL.encode()),
        "segmentation": "outer 10ms RMS threshold max(.002,3*20th percentile),250ms padding; internal pauses retained",
        "api_ceiling_usd": 10,
        "reservation_per_call_usd": RESERVATION,
        "warning": "Previously diagnosed UWB regression corpus, not a pristine external test.",
    }
    dump(directory / "plan.json", plan)
    dump(directory / "private-audit.json", private_audit)
    dump(directory / "manifest.json", manifest)
    dump(directory / "baseline.json", baseline)
    freeze(directory)
    print(
        json.dumps(
            {
                "audit_development": len(audit),
                "confirmation": len(confirmation),
                "reserve": len(reserve),
            }
        )
    )


class Budget:
    def __init__(self, path, ceiling=10):
        self.path, self.ceiling, self.lock = path, ceiling, threading.Lock()
        self.data = json.loads(path.read_text()) if path.exists() else {"reservations": []}

    def reserve(self, key):
        with self.lock, self.path.with_suffix(".lock").open("a") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            self.data = json.loads(self.path.read_text()) if self.path.exists() else {"reservations": []}
            if (len(self.data["reservations"]) + 1) * RESERVATION > self.ceiling:
                raise RuntimeError("API ceiling reached before request; stopping")
            self.data["reservations"].append({"key": key, "max_usd": RESERVATION})
            dump(self.path, self.data)  # Crash/timeout remains reserved; never refund unknown usage.


def run_gemini(directory, subset, variant):
    from google import genai
    from google.genai import types
    from keys import ensure_gemini_key
    from pydantic import BaseModel, Field

    class Transcript(BaseModel):
        transcript: str
        uncertain_words: list[str] = Field(default_factory=list)
        audio_quality: float = Field(ge=0, le=1)

    ensure_gemini_key()
    client = genai.Client(
        http_options=types.HttpOptions(timeout=45000, retry_options=types.HttpRetryOptions(attempts=1))
    )
    plan, manifest, _baseline = load_frozen(directory)
    ids = set(plan[subset])
    rows = [r for r in manifest if r["id"] in ids]
    budget = Budget(directory / "budget.json")
    cache = directory / "cache"
    cache.mkdir(exist_ok=True)
    instruction = ASR_INSTRUCTIONS if variant in ("control", "domain") else LITERAL
    context = DOMAIN if variant == "domain" else GENERIC_PROMPT
    prompt = f"{instruction}\n\nContext and vocabulary: {context}"
    if len(prompt.encode()) > 3000:
        raise ValueError("Prompt exceeds conservative input bound")

    def call(row):
        audio, rate = sf.read(row["file"], dtype="float32")
        if len(audio) / rate > 20:
            raise ValueError("Audio exceeds conservative input bound")
        start, end = boundaries(audio, rate) if variant == "segmented" else (0, len(audio))
        output = io.BytesIO()
        sf.write(output, audio[start:end], rate, format="WAV", subtype="PCM_16")
        data = output.getvalue()
        config_key = {
            "model": MODEL,
            "prompt": prompt,
            "max_output_tokens": MAX_OUTPUT,
            "temperature": 0,
            "thinking": "low",
            "schema": "transcript/uncertain_words/audio_quality-v1",
        }
        key = digest(data + json.dumps(config_key, sort_keys=True).encode())
        path = cache / (key + ".json")
        if path.exists():
            result = json.loads(path.read_text())
            return {**result, "id": row["id"], "variant": variant, "cached": True}
        budget.reserve(key)
        t0 = time.perf_counter()
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Part.from_bytes(data=data, mime_type="audio/wav"),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=Transcript,
                    max_output_tokens=MAX_OUTPUT,
                    thinking_config=types.ThinkingConfig(thinking_level="low"),
                ),
            )
            latency = time.perf_counter() - t0
            usage = response.usage_metadata.model_dump(mode="json") if response.usage_metadata else {}
            finish = str(response.candidates[0].finish_reason) if response.candidates else "NO_CANDIDATE"
            if finish not in ("FinishReason.STOP", "STOP") or not response.text:
                raise ValueError("Incomplete model output: " + finish)
            parsed = Transcript.model_validate_json(response.text)
            hypothesis = normalize_for_wer(parsed.transcript)
            input_tokens = usage.get("prompt_token_count") or 0
            output_tokens = (usage.get("candidates_token_count") or 0) + (usage.get("thoughts_token_count") or 0)
            result = {
                "id": row["id"],
                "variant": variant,
                "hypothesis": hypothesis,
                "text": parsed.transcript,
                "latency_s": latency,
                "input_sha256": digest(data),
                "start_sample": start,
                "end_sample": end,
                "sample_rate": rate,
                "usage": usage,
                "estimated_usd": input_tokens * INPUT_RATE + output_tokens * OUTPUT_RATE,
                "cached": False,
                "error": None,
            }
            if input_tokens > MAX_INPUT or output_tokens > MAX_OUTPUT:
                raise RuntimeError("Provider token usage exceeded the reservation assumption")
        except Exception as error:  # noqa: BLE001 - persist explicit failures; never interpret them as successful silence
            result = {
                "id": row["id"],
                "variant": variant,
                "error": type(error).__name__ + ": " + str(error)[:180],
                "hypothesis": "",
                "latency_s": time.perf_counter() - t0,
                "estimated_usd": None,
                "cached": False,
            }
        dump(path, result)
        return result

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(call, rows))
    dump(directory / f"{subset}-{variant}.json", results)
    print(
        json.dumps(
            {
                "subset": subset,
                "variant": variant,
                "n": len(results),
                "errors": sum(bool(r["error"]) for r in results),
                "estimated_usd": sum(r["estimated_usd"] or 0 for r in results if not r["cached"]),
                "reservations_usd": len(budget.data["reservations"]) * RESERVATION,
            }
        )
    )


LOCAL_SETTINGS = {
    "device": "cpu",
    "compute_type": "int8",
    "cpu_threads": 4,
    "language": "en",
    "beam_size": 5,
    "condition_on_previous_text": False,
    "temperature": 0,
    "vad_filter": False,
}


def local_identity(model_path):
    files = {}
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "preprocessor_config.json"):
        path = model_path / name
        if not path.exists():
            if name in ("vocabulary.txt", "preprocessor_config.json"):
                files[name] = None
                continue
            raise ValueError("Missing local model file: " + name)
        with path.open("rb") as source:
            files[name] = hashlib.file_digest(source, "sha256").hexdigest()
    return {
        "model_files_sha256": files,
        "settings": LOCAL_SETTINGS,
        "packages": {
            name: importlib.metadata.version(name) for name in ("faster-whisper", "ctranslate2", "scipy", "soundfile")
        },
        "input_decoder": "soundfile.float32.mono.scipy.resample_poly.to_16000.v1",
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


def validate_local(rows, manifest, identity):
    selected = {row["id"]: row for row in manifest}
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)) or not set(ids) <= set(selected):
        raise ValueError("Duplicate or unexpected local result ID")
    identity_hash = digest(json.dumps(identity, sort_keys=True).encode())
    for row in rows:
        if row.get("identity_sha256") != identity_hash or row.get("input_sha256") != selected[row["id"]]["pcm_sha256"]:
            raise ValueError("Local result model/input identity mismatch")
        if row.get("error"):
            if row["hypothesis"] != "":
                raise ValueError("Failed local output must have empty hypothesis")
        elif row["hypothesis"] != normalize_for_wer(row["text"]):
            raise ValueError("Local result normalization mismatch")


def run_local(directory, model_path):
    from faster_whisper import WhisperModel

    with (directory / "local.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        local_plan, rows, _baseline = load_frozen(directory)
        selected = set(local_plan["audit_development"] + local_plan["confirmation"])
        rows = [row for row in rows if row["id"] in selected]
        identity = local_identity(model_path)
        identity_path = directory / "local-identity.json"
        output = directory / "local-medium.jsonl"
        if identity_path.exists():
            if json.loads(identity_path.read_text()) != identity:
                raise ValueError("Local model/runtime/settings changed; use a new experiment")
        elif output.exists():
            raise ValueError("Unsealed local results cannot be resumed")
        else:
            dump(identity_path, identity)
        existing = read_jsonl(output) if output.exists() else []
        validate_local(existing, rows, identity)
        identity_hash = digest(json.dumps(identity, sort_keys=True).encode())
        done = {r["id"] for r in existing}
        t0 = time.perf_counter()
        model = WhisperModel(str(model_path), device="cpu", compute_type="int8", cpu_threads=4)
        load = time.perf_counter() - t0
        with output.open("a") as target:
            for row in rows:
                if row["id"] in done:
                    continue
                t0 = time.perf_counter()
                try:
                    settings = {
                        key: value
                        for key, value in LOCAL_SETTINGS.items()
                        if key not in ("device", "compute_type", "cpu_threads")
                    }
                    audio, rate = sf.read(row["file"], dtype="float32")
                    if audio.ndim != 1 or not np.isfinite(audio).all():
                        raise ValueError("Expected finite mono PCM")
                    divisor = math.gcd(rate, 16000)
                    audio = resample_poly(audio, 16000 // divisor, rate // divisor).astype(np.float32)
                    segments, _info = model.transcribe(audio, **settings)
                    text = " ".join(segment.text.strip() for segment in segments).strip()
                    result = {
                        "id": row["id"],
                        "text": text,
                        "hypothesis": normalize_for_wer(text),
                        "latency_s": time.perf_counter() - t0,
                        "load_s": load,
                        "error": None,
                    }
                except Exception as error:  # noqa: BLE001 - persist explicit failure
                    result = {
                        "id": row["id"],
                        "hypothesis": "",
                        "error": type(error).__name__ + ": " + str(error)[:180],
                        "latency_s": time.perf_counter() - t0,
                    }
                result.update(identity_sha256=identity_hash, input_sha256=row["pcm_sha256"])
                target.write(json.dumps(result) + "\n")
                target.flush()
                done.add(row["id"])
                if len(done) % 10 == 0:
                    print("local completed", len(done), flush=True)


def measure(rows, baseline):
    refs = [baseline[r["id"]]["reference"] for r in rows]
    hyps = [r["hypothesis"] for r in rows]
    score = jiwer.process_words(refs, hyps)
    numeric_rows = [(ref, hyp) for ref, hyp in zip(refs, hyps, strict=True) if numeric(ref)]
    successful = [r for r in rows if not r.get("error") and r.get("latency_s") is not None]
    times = sorted(r["latency_s"] for r in successful)
    fresh_times = sorted(r["latency_s"] for r in successful if not r.get("cached", False))
    return {
        "n": len(rows),
        "wer": score.wer,
        "reference_tokens": score.hits + score.substitutions + score.deletions,
        "substitutions": score.substitutions,
        "deletions": score.deletions,
        "insertions": score.insertions,
        "errors": sum(bool(r.get("error")) for r in rows),
        "empty_hypotheses": sum(not h for h in hyps),
        "numeric_sequence_proxy": {
            "eligible": len(numeric_rows),
            "exact": sum(numeric(ref) == numeric(hyp) for ref, hyp in numeric_rows),
        },
        "stored_success_latency_n": len(times),
        "stored_success_median_latency_s": statistics.median(times) if times else None,
        "stored_success_p95_latency_s": times[math.ceil(len(times) * 0.95) - 1] if times else None,
        "uncached_success_latency_n": len(fresh_times),
        "uncached_success_median_latency_s": statistics.median(fresh_times) if fresh_times else None,
        "uncached_success_p95_latency_s": fresh_times[math.ceil(len(fresh_times) * 0.95) - 1] if fresh_times else None,
        "cached_results": sum(bool(r.get("cached")) for r in rows),
    }


def report(directory, output):
    plan, manifest, baseline = load_frozen(directory)
    local = read_jsonl(directory / "local-medium.jsonl") if (directory / "local-medium.jsonl").exists() else []
    result = {
        "plan_sha256": digest((directory / "plan.json").read_bytes()),
        "subsets": {},
        "cost_note": "API estimates from token metadata and 2026-10-11 standard rates, not billing receipts; unknown/failure usage remains conservatively reserved.",
    }
    if local:
        identity = json.loads((directory / "local-identity.json").read_text())
        selected = set(plan["audit_development"] + plan["confirmation"])
        validate_local(local, [row for row in manifest if row["id"] in selected], identity)
        result["local_provenance"] = identity
    for subset in ("audit_development", "confirmation", "reserve"):
        ids = set(plan[subset])
        variants = {
            "cached_baseline": [
                {
                    "id": key,
                    "hypothesis": r["hypothesis"],
                    "latency_s": r["asr"]["latency_s"],
                    "cached": True,
                }
                for key, r in baseline.items()
                if key in ids
            ]
        }
        if {r["id"] for r in local if r["id"] in ids} == ids:
            variants["local_medium"] = [r for r in local if r["id"] in ids]
        for variant in ("control", "literal", "segmented", "domain"):
            path = directory / f"{subset}-{variant}.json"
            if path.exists():
                rows = json.loads(path.read_text())
                if len(rows) != len(ids) or {r["id"] for r in rows} != ids:
                    raise ValueError("Incomplete or duplicate experiment subset")
                variants[variant] = rows
        result["subsets"][subset] = {key: measure(rows, baseline) for key, rows in variants.items()}
    if (directory / "budget.json").exists():
        reservations = json.loads((directory / "budget.json").read_text())["reservations"]
        cache = [json.loads(path.read_text()) for path in (directory / "cache").glob("*.json")]
        result["cost"] = {
            "reserved_calls": len(reservations),
            "conservative_reserved_usd": len(reservations) * RESERVATION,
            "estimated_successful_usd": sum(r.get("estimated_usd") or 0 for r in cache),
            "unknown_usage_calls": sum(r.get("estimated_usd") is None for r in cache),
            "input_usd_per_million": 0.75,
            "output_usd_per_million": 3.75,
        }
    dump(output, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "gemini", "local", "report"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--subset", choices=["audit_development", "confirmation", "reserve"])
    parser.add_argument("--variant", choices=["control", "literal", "segmented", "domain"])
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.directory, args.source)
    elif args.command == "gemini":
        run_gemini(args.directory, args.subset, args.variant)
    elif args.command == "local":
        run_local(args.directory, args.model_path)
    else:
        report(args.directory, args.output)
