"""Explicit, reference-blind model-assisted audio review; not human adjudication."""

import argparse
import fcntl
import json
import time
from pathlib import Path
from typing import Literal

import soundfile as sf
from pydantic import BaseModel, Field

from experiment import (
    INPUT_RATE,
    MAX_INPUT,
    MAX_OUTPUT,
    MODEL,
    OUTPUT_RATE,
    RESERVATION,
    Budget,
    digest,
    dump,
    load_frozen,
)

PROMPT = (
    "Review this short aviation radio recording without any reference transcript. "
    "Transcribe only audible speech, preserving repetitions and original languages; do not translate. "
    "Use [?] for unintelligible material; do not reconstruct a standard clearance. "
    "Identify the languages and approximate time spans. Extract every audible callsign and critical numeric field: "
    "heading, altitude, frequency, runway, QNH, time, speed, squawk, other numbers. "
    "For each field record the spoken wording and a canonical value preserving digit order, leading zeros, "
    "callsign letters, decimal frequency boundaries, and explicitly spoken units. "
    "Never infer a field type, unit, number, or airline from convention. "
    "If a field is unclear, set its value to null, record plausible alternatives only if audible, "
    "and mark it uncertain. Empty fields are allowed when none are audible. "
    "All times are approximate seconds relative to this clip. Describe limitations in cautions. "
    "Your output is model-assisted evidence, not validated ground truth."
)


class Span(BaseModel):
    start_s: float = Field(ge=0, le=20)
    end_s: float = Field(ge=0, le=20)
    language: str
    transcript: str


class CriticalField(BaseModel):
    kind: Literal["callsign", "heading", "altitude", "frequency", "runway", "qnh", "time", "speed", "squawk", "other"]
    spoken: str
    value: str | None
    alternatives: list[str]
    start_s: float = Field(ge=0, le=20)
    end_s: float = Field(ge=0, le=20)
    certainty: Literal["clear", "uncertain"]


class AudioReview(BaseModel):
    transcript: str
    languages: list[str]
    spans: list[Span]
    fields: list[CriticalField]
    cautions: list[str]


def protocol(source):
    plan, _rows, _baseline = load_frozen(source)
    parent = (source / "budget.json").read_bytes()
    previous = sum(r["max_usd"] for r in json.loads(parent)["reservations"])
    ceiling = min(25 * RESERVATION, 10 - previous)
    if ceiling < 25 * RESERVATION - 1e-9:
        raise ValueError("Insufficient conservative budget for 25 single attempts")
    return {
        "stage": "User-authorized reference-blind Gemini-assisted audio audit; not prompt tuning or human adjudication",
        "ids": plan["audit_development"],
        "source_freeze_sha256": digest((source / "freeze.json").read_bytes()),
        "parent_budget_sha256": digest(parent),
        "previous_reserved_usd": previous,
        "new_ceiling_usd": ceiling,
        "model": MODEL,
        "prompt": PROMPT,
        "schema": AudioReview.model_json_schema(),
        "max_output_tokens": MAX_OUTPUT,
        "max_input_tokens_assumption": MAX_INPUT,
        "thinking": "low",
        "temperature": 0,
        "no_references_or_prior_outputs_sent": True,
    }


def run(source, directory):
    from google import genai
    from google.genai import types
    from keys import ensure_gemini_key

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        expected = protocol(source)
        path = directory / "protocol.json"
        if path.exists():
            if json.loads(path.read_text()) != expected:
                raise ValueError("Audit protocol or parent inputs changed")
        else:
            if list(directory.glob("clip-*.json")):
                raise ValueError("Unsealed results")
            dump(path, expected)
        _plan, rows, _baseline = load_frozen(source)
        by_id = {r["id"]: r for r in rows}
        budget = Budget(directory / "budget.json", ceiling=expected["new_ceiling_usd"] + 1e-12)
        ensure_gemini_key()
        client = genai.Client(
            http_options=types.HttpOptions(timeout=60000, retry_options=types.HttpRetryOptions(attempts=1))
        )
        for index, key in enumerate(expected["ids"]):
            result_path = directory / f"clip-{index:02d}.json"
            row = by_id[key]
            if result_path.exists():
                stored = json.loads(result_path.read_text())
                if (
                    stored["id"] != key
                    or stored["protocol_sha256"] != digest(path.read_bytes())
                    or stored["pcm_sha256"] != row["pcm_sha256"]
                ):
                    raise ValueError("Audit result identity changed")
                continue  # Never rerun a failure or a completed review.
            data = Path(row["file"]).read_bytes()
            duration = sf.info(row["file"]).duration
            if duration > 20 or len(PROMPT.encode()) > 3000:
                raise ValueError("Input exceeds reservation assumptions")
            if digest((source / "budget.json").read_bytes()) != expected["parent_budget_sha256"]:
                raise ValueError("Parent budget changed")
            request_key = digest(data + path.read_bytes())
            prior = (
                json.loads((directory / "budget.json").read_text())["reservations"]
                if (directory / "budget.json").exists()
                else []
            )
            if any(r["key"] == request_key for r in prior):
                raise RuntimeError("Previously reserved attempt without result; do not retry unknown usage")
            budget.reserve(request_key)
            started = time.perf_counter()
            result = {
                "id": key,
                "pcm_sha256": row["pcm_sha256"],
                "protocol_sha256": digest(path.read_bytes()),
                "duration_s": duration,
                "error": None,
                "estimated_usd": None,
            }
            try:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=[types.Part.from_bytes(data=data, mime_type="audio/wav"), PROMPT],
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json",
                        response_schema=AudioReview,
                        max_output_tokens=MAX_OUTPUT,
                        thinking_config=types.ThinkingConfig(thinking_level="low"),
                    ),
                )
                usage = response.usage_metadata.model_dump(mode="json") if response.usage_metadata else {}
                result["usage"] = usage
                input_tokens = usage.get("prompt_token_count") or 0
                output_tokens = (usage.get("candidates_token_count") or 0) + (usage.get("thoughts_token_count") or 0)
                if input_tokens > MAX_INPUT or output_tokens > MAX_OUTPUT:
                    raise RuntimeError("Token reservation assumption exceeded")
                if not usage or not input_tokens:
                    raise RuntimeError("Missing usage metadata; retain unknown charge")
                result["estimated_usd"] = input_tokens * INPUT_RATE + output_tokens * OUTPUT_RATE
                finish = str(response.candidates[0].finish_reason) if response.candidates else "NO_CANDIDATE"
                if finish not in ("FinishReason.STOP", "STOP") or not response.text:
                    raise ValueError("Incomplete model review: " + finish)
                parsed = AudioReview.model_validate_json(response.text)
                for span in [*parsed.spans, *parsed.fields]:
                    if span.end_s < span.start_s or span.end_s > duration + 0.5:
                        raise ValueError("Invalid approximate span bounds")
                result["review"] = parsed.model_dump()
            except Exception as error:  # noqa: BLE001 - explicit failed attempts, never automatic retry
                result["error"] = type(error).__name__ + ": " + str(error)[:180]
            result["latency_s"] = time.perf_counter() - started
            dump(result_path, result)
            print(
                json.dumps(
                    {
                        "completed": index + 1,
                        "error": result["error"],
                        "reserved_usd": len(budget.data["reservations"]) * RESERVATION,
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
