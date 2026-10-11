"""Gemini function calling: pick a template, never write words.

The model sees the ParsedTransmission plus desk state and may only call
``choose_template(template_id, slots, reason)`` or ``handoff(reason)``. Our code validates the slots; invalid
output falls back to SAY_AGAIN, an API failure falls back to handoff. Nothing the model emits as free text
is ever spoken: only ``templates.render`` produces speech.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .desk import DeskState
from .models import ParsedTransmission
from .policy import PolicyDecision
from .templates import MODEL_SELECTABLE, POSITIONS, TEMPLATES, SlotError, TemplateId, validate_slots

DEFAULT_MODEL = "gemini-3.5-flash-lite"  # provider-apis policy default for latency-sensitive calls
CACHE_DIR = (
    Path(os.environ.get("LANDED_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache")) / "llm"
)

SYSTEM = (
    "You are the template picker for Landed, a SIMULATED helicopter desk assistant. You never write "
    "spoken text. You must call exactly one function: choose_template(template_id, slots, reason) with one "
    "of the whitelisted templates, or handoff(reason) if the request is anything other than a routine "
    "check-in, position report or readback. Never issue clearances, runway or approach instructions, or "
    "altitude or heading assignments. A check-in gets ACK_CHECKIN. A plain position report or readback gets "
    "REPORT_ACK. A pilot who states their destination or that they are landing (a routine declaration, not a "
    "request) gets TRAFFIC if the desk traffic list has an entry, otherwise REPORT_ACK. "
    "Fill every required slot of the chosen template. "
    "Use only the callsign given in 'aircraft' and only values present in "
    "the desk state. Templates and slots:\n"
    "- ACK_CHECKIN: reg, position (id), altimeter_inhg, optional report_point (id). Reply to a check-in.\n"
    "- CORRIDOR_ENTRY: reg, corridor (Hudson|East River), direction (north|south), reporting_point (id on that corridor).\n"
    "- REPORT_ACK: reg. Reply to a position report or readback that matches ADS-B.\n"
    "- TRAFFIC: reg, clock (1-12), distance_nm, traffic_type (helicopter|airplane|jet), altitude_ft (multiple of 100). "
    "Only from the 'traffic' list.\n"
    "- SAY_AGAIN: optional reg, what (transmission|callsign).\n"
    f"Position ids: {', '.join(POSITIONS)}."
)

_SLOT_PROPS = {
    "reg": {"type": "string"},
    "position": {"type": "string"},
    "altimeter_inhg": {"type": "number"},
    "report_point": {"type": "string"},
    "corridor": {"type": "string"},
    "direction": {"type": "string"},
    "reporting_point": {"type": "string"},
    "clock": {"type": "integer"},
    "distance_nm": {"type": "number"},
    "traffic_type": {"type": "string"},
    "altitude_ft": {"type": "integer"},
    "what": {"type": "string"},
}

TOOLS = [
    {
        "name": "choose_template",
        "description": "Pick one whitelisted template and fill its slots.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "template_id": {"type": "string", "enum": [t.value for t in MODEL_SELECTABLE]},
                "slots": {"type": "object", "properties": _SLOT_PROPS},
                "reason": {"type": "string"},
            },
            "required": ["template_id", "slots", "reason"],
        },
    },
    {
        "name": "handoff",
        "description": "Hand this transmission to the human controller.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


@dataclass
class Choice:
    kind: str  # "template" | "handoff"
    template_id: TemplateId | None = None
    slots: dict[str, Any] | None = None
    reason: str = ""
    source: str = "gemini"  # "gemini" | "fallback"


# A model call returns {"name": ..., "args": {...}} or None.
ModelCall = Callable[[str], dict[str, Any] | None]


def build_prompt(parsed: ParsedTransmission, desk: DeskState, decision: PolicyDecision) -> str:
    return json.dumps(
        {
            "aircraft": decision.reg,
            "transmission": {
                "raw_text": parsed.raw_text,
                "intent": parsed.intent,
                "slots": parsed.slots.model_dump(exclude_none=True),
            },
            "desk": {
                "roster": desk.roster,
                "altimeter_inhg": desk.altimeter_inhg,
                "traffic": desk.traffic,
                "adsb": {r: p.model_dump(exclude_none=True) for r, p in desk.positions.items()},
            },
        },
        sort_keys=True,
    )


def gemini_model_call(model: str = DEFAULT_MODEL, use_cache: bool = True) -> ModelCall:
    """Real Gemini call. The key comes from the server process environment only."""
    from google.genai import types

    client = None

    def call(prompt: str) -> dict[str, Any] | None:
        nonlocal client
        key = hashlib.sha256(f"{model}|{SYSTEM}|{prompt}".encode()).hexdigest()
        path = CACHE_DIR / f"{key}.json"
        if use_cache and path.exists():
            return json.loads(path.read_text())
        if client is None:
            from google import genai

            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=[types.Tool(function_declarations=TOOLS)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.ANY)
            ),
            temperature=0.0,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        )
        resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
        calls = resp.function_calls or []
        out = {"name": calls[0].name, "args": dict(calls[0].args or {})} if calls else None
        if use_cache and out is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out))
        return out

    return call


def choose(parsed: ParsedTransmission, desk: DeskState, decision: PolicyDecision, call: ModelCall) -> Choice:
    """Ask the model for a template and validate everything it says. Free text is discarded."""
    try:
        out = call(build_prompt(parsed, desk, decision))
    except Exception as e:
        return Choice("handoff", reason=f"model unavailable ({type(e).__name__})", source="fallback")
    if not out:
        return _say_again(decision, "model made no function call")
    name, args = out.get("name"), out.get("args") or {}
    if name == "handoff":
        return Choice("handoff", reason=str(args.get("reason", ""))[:200])
    if name != "choose_template":
        return _say_again(decision, f"unknown function {name!r}")
    tid, slots = args.get("template_id"), args.get("slots")
    reason = str(args.get("reason", ""))[:200]
    if tid not in {t.value for t in MODEL_SELECTABLE} or not isinstance(slots, dict):
        return _say_again(decision, f"template {tid!r} not selectable")
    # Drop nulls and keys the template has no slot for (the tool schema is one shared bag of slots);
    # every remaining value is still strictly validated.
    allowed = TEMPLATES[TemplateId(tid)].slots_model.model_fields
    slots = {k: v for k, v in slots.items() if v is not None and k in allowed}
    # The model sometimes returns a valid position id in the wrong case ("jrb" for "JRB"); map it back.
    by_lower = {k.lower(): k for k in POSITIONS}
    for key in ("position", "report_point", "reporting_point"):
        if isinstance(slots.get(key), str) and slots[key] not in POSITIONS:
            slots[key] = by_lower.get(slots[key].lower(), slots[key])
    if tid == TemplateId.TRAFFIC:
        # Complete omitted traffic slots from the desk's own traffic list (data, never model text).
        for t in desk.traffic:
            if all(slots[k] == t.get(k) for k in slots if k in t):
                slots = {**{k: v for k, v in t.items() if k in allowed}, **slots}
                break
    try:
        model = validate_slots(tid, slots, desk.roster_set)
    except SlotError as e:
        return _say_again(decision, f"invalid slots: {str(e).splitlines()[0]}")
    reg = getattr(model, "reg", None)
    if tid != TemplateId.SAY_AGAIN and reg != decision.reg:
        return _say_again(decision, f"model used callsign {reg!r}, expected {decision.reg!r}")
    if tid == TemplateId.SAY_AGAIN and reg not in (None, decision.reg):
        return _say_again(decision, "model used the wrong callsign")
    return Choice("template", TemplateId(tid), model.model_dump(exclude_none=True), reason)


def _say_again(decision: PolicyDecision, why: str) -> Choice:
    slots: dict[str, Any] = {"what": "transmission"}
    if decision.reg:
        slots["reg"] = decision.reg
    return Choice("template", TemplateId.SAY_AGAIN, slots, f"fallback: {why}", source="fallback")
