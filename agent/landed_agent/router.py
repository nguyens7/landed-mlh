"""Typed decision router: label + probabilities for one transmission. Advisory and fail-safe.

Providers (select with ``LANDED_ROUTER=decisions|jev|gemini|off``):

- ``DecisionsRouter``: OpenAI Decisions (``POST /v1/decisions``, ``gpt-6-luna``, public beta).
- ``JevRouter``: TypeSafe Jev (``POST /v1/systemone``). Needs ``TYPESAFE_API_KEY``, else ``ProviderUnavailable``.
- ``GeminiEnumRouter``: fallback, Gemini structured output with an enum label and self-reported probabilities
  (not calibrated).

Fixed thresholds (see ``combine``). The router can only make the outcome MORE cautious: it never clears a
hard handoff trigger, never undoes the emergency lock, never promotes approval to auto, and never selects
or authorizes words (speech still comes only from ``templates.render``). Timeout (800 ms), any error,
malformed output, or an ``unknown`` label sets ``abstained=True``, which means the approval card, never auto.
Keys come from the process environment only.

The thresholds (0.5 attention, 0.85 routine) are PROVISIONAL: they have not been validated on our own labeled
data, and a provider's "confidence" or probability measures concentration of its distribution, not proof of
correctness. Thresholds and execution live here in ordinary code, not in the provider.
Failure causes are kept apart in the abstention reason (provider unavailable / timeout / HTTP error /
malformed output / refusal); every one of them abstains, which means the approval card.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .desk import DeskState
from .models import ParsedTransmission

Label = Literal["routine", "needs_review", "emergency", "unknown"]
LABELS: tuple[str, ...] = ("routine", "needs_review", "emergency", "unknown")

# ---- fixed, documented thresholds
ATTENTION_HANDOFF_P = 0.5  # attention_p >= this, or label emergency -> handoff
ROUTINE_AUTO_P = 0.85  # label routine with p >= this (and no hard trigger) -> policy tier stands (auto)
TIMEOUT_S = 0.8
GEMINI_MIN_DEADLINE_MS = 10_000

DECISIONS_URL = "https://api.openai.com/v1/decisions"
DECISIONS_MODEL = "gpt-6-luna"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
GEMINI_ROUTER_MODEL = "gemini-3.5-flash-lite"

CACHE_DIR = (
    Path(os.environ.get("LANDED_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache")) / "router"
)

LABEL_DESCRIPTIONS = {
    "routine": "A plain check-in, position report, or readback that needs no controller judgment.",
    "needs_review": "A request, ambiguity, weather, altitude or route question, or anything a controller should look at.",
    "emergency": "A distress call, declared emergency, or mention of an urgent medical, fuel or mechanical problem.",
    "unknown": "The transmission cannot be understood well enough to classify.",
}
LABEL_INSTRUCTIONS = "Classify this simulated helicopter radio call."
ATTENTION_INSTRUCTIONS = "this radio call needs immediate controller attention"


class ProviderUnavailable(Exception):
    """The provider cannot be used right now (no key, not enabled for the account, 403/404)."""


@dataclass
class RouterDecision:
    label: str = "unknown"
    probabilities: dict[str, float] = field(default_factory=dict)
    attention_p: float = 0.0
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    abstained: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def label_p(self) -> float:
        return self.probabilities.get(self.label, 0.0)


class Router(Protocol):
    provider: str
    model: str

    def route(self, parsed: ParsedTransmission, desk: DeskState) -> RouterDecision: ...


# An HTTP POST: (url, headers, json_body, timeout_s) -> (status_code, json_or_None). Injectable for tests.
HttpPost = Callable[[str, dict[str, str], dict[str, Any], float], tuple[int, Any]]


def _httpx_post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> tuple[int, Any]:
    import httpx

    r = httpx.post(url, headers=headers, json=body, timeout=timeout)
    try:
        data = r.json()
    except ValueError:
        data = None
    return r.status_code, data


def router_input(parsed: ParsedTransmission, desk: DeskState) -> str:
    """Only the structured fields plus the raw transcript. No roster contents, no free-text agent output."""
    reg = parsed.callsign.snapped_to
    return json.dumps(
        {
            "transcript": parsed.raw_text,
            "intent": parsed.intent,
            "slots": parsed.slots.model_dump(exclude_none=True),
            "callsign_on_roster": bool(reg and reg in desk.roster_set),
            "callsign_ambiguous_with": parsed.callsign.ambiguous_with,
            "asr_confidence": parsed.asr_confidence,
            "parse_confidence": parsed.parse_confidence,
            "parser_flagged_emergency": parsed.emergency,
            "active_alerts_on_desk": len(desk.alerts),
        },
        sort_keys=True,
    )


def cache_enabled() -> bool:
    return os.environ.get("LANDED_DEMO_CACHE") == "1" or os.environ.get("LANDED_ROUTER_CACHE") == "1"


def _abstain(provider: str, model: str, why: str, t0: float) -> RouterDecision:
    return RouterDecision(
        provider=provider, model=model, abstained=True, reason=why, latency_ms=round((time.perf_counter() - t0) * 1000)
    )  # fmt: skip


def _finish(
    label: str, probs: dict[str, float], attention: float, provider: str, model: str, t0: float
) -> RouterDecision:
    """Validate provider output. Anything malformed or ``unknown`` becomes an abstention."""
    ms = round((time.perf_counter() - t0) * 1000)
    ok = (
        label in LABELS
        and isinstance(attention, int | float)
        and 0.0 <= attention <= 1.0
        and all(k in LABELS and isinstance(v, int | float) and 0.0 <= v <= 1.0 for k, v in probs.items())
        and label in probs
    )
    if not ok:
        return RouterDecision(provider=provider, model=model, abstained=True, latency_ms=ms,
                              reason="malformed router output")  # fmt: skip
    d = RouterDecision(label, {k: float(v) for k, v in probs.items()}, float(attention), provider, model, ms)
    if label == "unknown":
        d.abstained, d.reason = True, "router label unknown"
    return d


class _Base:
    provider = ""
    model = ""

    def __init__(self, post: HttpPost | None = None, timeout_s: float = TIMEOUT_S, cache: bool | None = None):
        self._post = post or _httpx_post
        self.timeout_s = timeout_s
        self._cache = cache_enabled() if cache is None else cache

    def _call(self, text: str) -> RouterDecision:  # pragma: no cover - overridden
        raise NotImplementedError

    def route(self, parsed: ParsedTransmission, desk: DeskState) -> RouterDecision:
        text = router_input(parsed, desk)
        path = CACHE_DIR / (
            hashlib.sha256(f"{text}|{self.provider}|{self.model}".encode()).hexdigest() + ".json"
        )
        if self._cache and path.exists():
            try:
                return RouterDecision(**json.loads(path.read_text()))
            except (OSError, ValueError, TypeError):
                pass
        t0 = time.perf_counter()
        try:
            d = self._call(text)
        except ProviderUnavailable as e:
            d = _abstain(self.provider, self.model, f"provider unavailable: {e}", t0)
        except Exception as e:  # timeout, network, bad JSON shape: always fail safe
            kind = "timeout" if "timeout" in type(e).__name__.lower() else type(e).__name__
            d = _abstain(self.provider, self.model, kind, t0)
        if self._cache and not d.abstained:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(d.to_dict()))
            except OSError:
                pass
        return d


class DecisionsRouter(_Base):
    provider = "OpenAI Decisions"
    model = DECISIONS_MODEL

    def __init__(self, api_key: str | None = None, **kw: Any):
        super().__init__(**kw)
        self._key = api_key

    def _call(self, text: str) -> RouterDecision:
        key = self._key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderUnavailable("OPENAI_API_KEY not set")
        body = {
            "model": self.model,
            "input": text,
            "questions": [
                {
                    "type": "choice",
                    "name": "label",
                    "instructions": LABEL_INSTRUCTIONS,
                    "choices": [{"value": k, "description": v} for k, v in LABEL_DESCRIPTIONS.items()],
                },
                {"type": "predicate", "name": "attention", "instructions": ATTENTION_INSTRUCTIONS},
            ],
        }
        t0 = time.perf_counter()
        status, data = self._post(DECISIONS_URL, {"Authorization": f"Bearer {key}"}, body, self.timeout_s)
        if status in (403, 404):
            raise ProviderUnavailable(f"HTTP {status} (Decisions API not enabled for this account)")
        if status != 200 or not isinstance(data, dict):
            return _abstain(self.provider, self.model, f"HTTP {status}", t0)
        answers = {a.get("name"): a for a in data.get("answers", []) if isinstance(a, dict)}
        lab, att = answers.get("label"), answers.get("attention")
        if not lab or not att or lab.get("type") == "refusal" or att.get("type") == "refusal":
            return _abstain(self.provider, self.model, "router refused or omitted a question", t0)
        probs = {p["value"]: p["probability"] for p in lab.get("probabilities", []) if "value" in p}
        return _finish(lab.get("choice"), probs, att.get("probability"), self.provider, self.model, t0)  # type: ignore[arg-type]


class JevRouter(_Base):
    provider = "TypeSafe Jev"
    model = JEV_MODEL

    def __init__(self, api_key: str | None = None, **kw: Any):
        super().__init__(**kw)
        self._key = api_key

    def _call(self, text: str) -> RouterDecision:
        key = self._key or os.environ.get("TYPESAFE_API_KEY")
        if not key:
            raise ProviderUnavailable("TYPESAFE_API_KEY not set")
        body = {
            "state": text,
            "model": self.model,
            "questions": {
                "label": {
                    "type": "choice",
                    "instructions": LABEL_INSTRUCTIONS,
                    "criteria": dict(LABEL_DESCRIPTIONS),
                },
                "attention": {"type": "noul", "instructions": ATTENTION_INSTRUCTIONS},
            },
        }
        t0 = time.perf_counter()
        status, data = self._post(JEV_URL, {"Authorization": f"Bearer {key}"}, body, self.timeout_s)
        if status in (401, 403, 404):
            raise ProviderUnavailable(f"HTTP {status}")
        if status != 200 or not isinstance(data, dict):
            return _abstain(self.provider, self.model, f"HTTP {status}", t0)
        ans = data.get("answers") or {}
        lab, att = ans.get("label"), ans.get("attention")
        if not isinstance(lab, dict) or not isinstance(att, dict):
            return _abstain(self.provider, self.model, "malformed router output", t0)
        return _finish(
            lab.get("choice"), lab.get("probabilities") or {}, att.get("noul"), self.provider, self.model, t0
        )  # type: ignore[arg-type]


class GeminiEnumRouter(_Base):
    """Fallback. Gemini returns an enum label plus self-reported probabilities (not calibrated)."""

    provider = "Gemini enum"
    model = GEMINI_ROUTER_MODEL

    def __init__(self, generate: Callable[[str], dict[str, Any]] | None = None, **kw: Any):
        super().__init__(**kw)
        self._generate = generate
        self._client: Any = None

    def _default_generate(self, text: str) -> dict[str, Any]:
        from google import genai
        from google.genai import types

        if self._client is None:
            self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        schema = {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": list(LABELS)},
                "label_probability": {"type": "number"},
                "attention_probability": {"type": "number"},
            },
            "required": ["label", "label_probability", "attention_probability"],
        }
        cfg = types.GenerateContentConfig(
            system_instruction=(
                "Classify a SIMULATED helicopter radio call. Labels: "
                + "; ".join(f"{k}: {v}" for k, v in LABEL_DESCRIPTIONS.items())
                + f" Also give the probability that {ATTENTION_INSTRUCTIONS}."
            ),
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0.0,
            seed=7,
            max_output_tokens=256,
            # The Gemini API rejects request deadlines under 10 s (ClientError), which made this router
            # abstain on every call. Use the API minimum; the measured latency is still recorded.
            http_options=types.HttpOptions(timeout=max(GEMINI_MIN_DEADLINE_MS, int(self.timeout_s * 1000))),
        )
        resp = self._client.models.generate_content(model=self.model, contents=text, config=cfg)
        return json.loads(resp.text)

    def _call(self, text: str) -> RouterDecision:
        if self._generate is None and not os.environ.get("GEMINI_API_KEY"):
            raise ProviderUnavailable("GEMINI_API_KEY not set")
        t0 = time.perf_counter()
        out = (self._generate or self._default_generate)(text)
        label = out.get("label")
        p = out.get("label_probability")
        probs = {label: p} if label in LABELS and isinstance(p, int | float) else {}
        return _finish(label, probs, out.get("attention_probability"), self.provider, self.model, t0)  # type: ignore[arg-type]


def router_mode() -> Literal["shadow", "enforce"]:
    """``LANDED_ROUTER_MODE``: shadow (default) annotates and logs the router's decision without changing the
    policy tier; enforce lets it make a decision more cautious. Enforce only after thresholds are validated."""
    return "enforce" if os.environ.get("LANDED_ROUTER_MODE", "").strip().lower() == "enforce" else "shadow"


def router_from_env() -> Router | None:
    """``LANDED_ROUTER``: decisions|jev|gemini|off. Default: decisions if OPENAI_API_KEY, else gemini if a
    Gemini key is present, else no router."""
    choice = os.environ.get("LANDED_ROUTER", "").strip().lower()
    if choice == "off":
        return None
    if not choice:
        if os.environ.get("OPENAI_API_KEY"):
            choice = "decisions"
        elif os.environ.get("GEMINI_API_KEY"):
            choice = "gemini"
        else:
            return None
    return {"decisions": DecisionsRouter, "jev": JevRouter, "gemini": GeminiEnumRouter}[choice]()


# ------------------------------------------------------------------ combination with policy

RouterTier = Literal["auto", "approval", "handoff"]


def combine(policy_tier: str, rd: RouterDecision, hard_trigger: bool = False) -> tuple[str, str]:
    """Return (tier, why). Only ever as cautious as, or more cautious than, ``policy_tier``.

    Order of caution: auto < approval < handoff. Emergency / suppressed / any hard trigger are decided by
    policy before this is called and are returned unchanged.
    """
    if policy_tier in ("emergency", "suppressed", "handoff") or hard_trigger:
        return policy_tier, "router cannot relax a policy decision"
    if rd.abstained:
        return ("approval" if policy_tier == "auto" else policy_tier), f"router abstained: {rd.reason}"
    if rd.attention_p >= ATTENTION_HANDOFF_P or rd.label == "emergency":
        return "handoff", f"router attention {rd.attention_p:.2f}, label {rd.label}"
    if rd.label == "routine" and rd.label_p >= ROUTINE_AUTO_P:
        return policy_tier, "router agrees routine"  # never promotes approval to auto
    return ("approval" if policy_tier == "auto" else policy_tier), f"router: {rd.label} {rd.label_p:.2f}"


def card_line(rd: dict[str, Any]) -> str:
    """The one-line display string used by docs and tests (the UI builds the same text)."""
    if rd.get("abstained"):
        return f"Router abstained: {rd.get('reason', '')}"
    return f"Router: {str(rd['label']).replace('_', ' ')} {rd.get('probabilities', {}).get(rd['label'], 0):.2f} ({rd['provider']}, {rd['model']})"
