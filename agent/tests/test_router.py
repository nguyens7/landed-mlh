"""Router: provider adapters (HTTP mocked), thresholds, and the only-more-cautious rules."""

from __future__ import annotations

import pytest
from conftest import make_parsed

from landed_agent import router as R
from landed_agent.agent import VoiceAgent
from landed_agent.router import (
    DecisionsRouter,
    GeminiEnumRouter,
    JevRouter,
    ProviderUnavailable,
    RouterDecision,
    combine,
    router_mode,
)

ACK = {
    "template_id": "ACK_CHECKIN",
    "slots": {"reg": "N2646X", "position": "JRB", "altimeter_inhg": 29.92},
    "reason": "routine",
}


def model_call(prompt):
    return {"name": "choose_template", "args": ACK}


def decisions_response(label="routine", p=0.97, attention=0.02):
    probs = [{"value": k, "probability": 0.01} for k in R.LABELS]
    for x in probs:
        if x["value"] == label:
            x["probability"] = p
    return 200, {
        "answers": [
            {"type": "choice", "name": "label", "choice": label, "probabilities": probs, "confidence": p},
            {"type": "predicate", "name": "attention", "probability": attention},
        ]
    }


def poster(status_data):
    calls = []

    def post(url, headers, body, timeout):
        calls.append((url, headers, body, timeout))
        if isinstance(status_data, Exception):
            raise status_data
        return status_data

    post.calls = calls  # type: ignore[attr-defined]
    return post


def rd(label="routine", p=0.97, attention=0.02, abstained=False):
    return RouterDecision(label, {label: p}, attention, "t", "m", 1, abstained, "x" if abstained else "")


# ------------------------------------------------------------------ Decisions adapter


def test_decisions_request_and_parse(desk):
    post = poster(decisions_response("needs_review", 0.91, 0.3))
    d = DecisionsRouter(api_key="k", post=post, cache=False).route(make_parsed(), desk)
    url, headers, body, timeout = post.calls[0]
    assert url.endswith("/v1/decisions") and body["model"] == "gpt-6-luna" and timeout == 0.8
    assert [q["name"] for q in body["questions"]] == ["label", "attention"]
    assert [c["value"] for c in body["questions"][0]["choices"]] == list(R.LABELS)
    assert "Authorization" in headers
    assert (d.label, d.probabilities["needs_review"], d.attention_p, d.abstained) == (
        "needs_review",
        0.91,
        0.3,
        False,
    )
    assert R.card_line(d.to_dict()) == "Router: needs review 0.91 (OpenAI Decisions, gpt-6-luna)"


def test_decisions_input_is_structured_only(desk):
    post = poster(decisions_response())
    DecisionsRouter(api_key="k", post=post, cache=False).route(make_parsed(), desk)
    text = post.calls[0][2]["input"]
    assert "N312LM" not in text and "transcript" in text


@pytest.mark.parametrize(
    "resp",
    [
        poster((200, {"answers": []})),
        poster((200, {"answers": [{"type": "refusal", "name": "label"}]})),
        poster((200, "junk")),
        poster((500, None)),
        poster(decisions_response("banana")),
        poster(decisions_response("routine", p=1.7)),
        poster(decisions_response("unknown", 0.9)),
        poster(TimeoutError("t")),
        poster(ConnectionError("down")),
    ],
)
def test_bad_output_abstains(resp, desk):
    d = DecisionsRouter(api_key="k", post=resp, cache=False).route(make_parsed(), desk)
    assert d.abstained and d.reason


@pytest.mark.parametrize("status", [403, 404])
def test_decisions_not_enabled_abstains(status, desk):
    post = poster((status, {"error": "x"}))
    d = DecisionsRouter(api_key="k", post=post, cache=False).route(make_parsed(), desk)
    assert d.abstained and "unavailable" in d.reason and str(status) in d.reason


def test_decisions_without_key_abstains(monkeypatch, desk):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    d = DecisionsRouter(post=poster(decisions_response()), cache=False).route(make_parsed(), desk)
    assert d.abstained


# ------------------------------------------------------------------ Jev adapter (mocked)

JEV_OK = (
    200,
    {
        "model": "jev-1.13.0",
        "answers": {
            "label": {
                "type": "choice",
                "choice": "needs_review",
                "confidence": 0.8,
                "probabilities": {"routine": 0.1, "needs_review": 0.85, "emergency": 0.05, "unknown": 0.0},
            },
            "attention": {"type": "noul", "noul": 0.7},
        },
    },
)


def test_jev_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable):
        JevRouter(post=poster(JEV_OK), cache=False)._call("x")


def test_jev_parse_mocked(monkeypatch, desk):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    post = poster(JEV_OK)
    d = JevRouter(post=post, cache=False).route(make_parsed(), desk)
    url, headers, body, _ = post.calls[0]
    assert url == "https://api.typesafe.ai/v1/systemone" and headers["Authorization"] == "Bearer k"
    assert body["questions"]["label"]["type"] == "choice"
    assert set(body["questions"]["label"]["criteria"]) == set(R.LABELS)
    assert (d.label, d.attention_p, d.provider, d.abstained) == ("needs_review", 0.7, "TypeSafe Jev", False)
    assert d.probabilities["needs_review"] == 0.85


def test_jev_without_key_route_abstains(monkeypatch, desk):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert JevRouter(post=poster(JEV_OK), cache=False).route(make_parsed(), desk).abstained


def test_gemini_enum_router(desk):
    def gen(text):
        return {"label": "routine", "label_probability": 0.95, "attention_probability": 0.05}

    d = GeminiEnumRouter(generate=gen, cache=False).route(make_parsed(), desk)
    assert d.label == "routine" and d.label_p == 0.95 and not d.abstained
    bad = GeminiEnumRouter(generate=lambda t: {"label": "??"}, cache=False).route(make_parsed(), desk)
    assert bad.abstained


def test_selection_from_env(monkeypatch):
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "LANDED_ROUTER"):
        monkeypatch.delenv(k, raising=False)
    assert R.router_from_env() is None
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert isinstance(R.router_from_env(), GeminiEnumRouter)
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    assert isinstance(R.router_from_env(), DecisionsRouter)
    monkeypatch.setenv("LANDED_ROUTER", "jev")
    assert isinstance(R.router_from_env(), JevRouter)
    monkeypatch.setenv("LANDED_ROUTER", "off")
    assert R.router_from_env() is None


def test_cache_replay(tmp_path, monkeypatch, desk):
    monkeypatch.setattr(R, "CACHE_DIR", tmp_path)
    post = poster(decisions_response())
    r = DecisionsRouter(api_key="k", post=post, cache=True)
    a = r.route(make_parsed(), desk)
    b = r.route(make_parsed(), desk)
    assert len(post.calls) == 1 and a.label == b.label
    bad = poster((500, None))  # an abstention is never cached
    DecisionsRouter(api_key="k", post=bad, cache=True).route(make_parsed("other text"), desk)
    DecisionsRouter(api_key="k", post=bad, cache=True).route(make_parsed("other text"), desk)
    assert len(bad.calls) == 2


# ------------------------------------------------------------------ thresholds (combine)


def test_thresholds():
    assert combine("auto", rd("routine", 0.85))[0] == "auto"
    assert combine("auto", rd("routine", 0.84))[0] == "approval"
    assert combine("auto", rd("needs_review", 0.99))[0] == "approval"
    assert combine("auto", rd("routine", 0.99, attention=0.5))[0] == "handoff"
    assert combine("auto", rd("routine", 0.99, attention=0.49))[0] == "auto"
    assert combine("auto", rd("emergency", 0.6, attention=0.1))[0] == "handoff"
    assert combine("approval", rd("routine", 0.99))[0] == "approval"  # never promoted to auto


def test_abstain_is_never_auto():
    assert combine("auto", rd(abstained=True))[0] == "approval"
    assert combine("approval", rd(abstained=True))[0] == "approval"


@pytest.mark.parametrize("tier", ["handoff", "emergency", "suppressed"])
@pytest.mark.parametrize("r", [rd("routine", 0.99), rd(abstained=True), rd("emergency", 0.9, 0.99)])
def test_router_never_relaxes_policy(tier, r):
    assert combine(tier, r)[0] == tier


# ------------------------------------------------------------------ end to end through VoiceAgent


@pytest.fixture(autouse=True)
def _enforce_mode(monkeypatch):
    # These tests cover the enforce semantics; shadow (the default) is tested separately below.
    monkeypatch.setenv("LANDED_ROUTER_MODE", "enforce")


class Fixed:
    provider, model = "t", "m"

    def __init__(self, d):
        self.d = d

    def route(self, parsed, desk):
        return self.d


def run(router_decision, parsed, desk):
    agent = VoiceAgent(model_call, router=Fixed(router_decision))
    return agent.handle_transmission(parsed, desk, 1000)


def test_routine_router_keeps_auto_and_records_fields(desk):
    [p] = run(rd("routine", 0.95), make_parsed(altitude_ft=500), desk)
    assert p.tier == "auto" and p.router["label"] == "routine" and p.router["provider"] == "t"


def test_abstain_sends_to_approval_card(desk):
    [p] = run(rd(abstained=True), make_parsed(altitude_ft=500), desk)
    assert p.tier == "approval" and p.status == "pending" and p.router["abstained"]


def test_attention_forces_handoff(desk):
    [p] = run(rd("needs_review", 0.9, attention=0.8), make_parsed(altitude_ft=500), desk)
    assert p.tier == "handoff" and p.template_id == "STANDBY_HANDOFF"


def test_router_cannot_clear_hard_handoff_trigger(desk):
    parsed = make_parsed(
        "MEDEVAC Two Six Four Six X-Ray, request direct College Point", intent="request_route"
    )
    [p] = run(rd("routine", 0.99, attention=0.0), parsed, desk)
    assert p.tier == "handoff" and "out_of_whitelist" in p.triggers and p.template_id == "STANDBY_HANDOFF"
    assert p.router["label"] == "routine"  # annotated, not obeyed


def test_router_cannot_clear_altitude_trigger(desk):
    [p] = run(rd("routine", 0.99), make_parsed(altitude_ft=1400), desk)
    assert p.tier == "handoff" and "altitude_class_b" in p.triggers


def test_router_cannot_override_emergency_lock(desk):
    parsed = make_parsed("MEDEVAC Two Six Four Six X-Ray, MAYDAY, engine failure", intent="emergency")
    agent = VoiceAgent(model_call, router=Fixed(rd("routine", 0.99)))
    [p, _ops] = agent.handle_transmission(parsed, desk, 1000)
    assert p.tier == "emergency" and desk.locked and p.router is None
    [q] = agent.handle_transmission(make_parsed(altitude_ft=500), desk, 2000)
    assert q.tier == "suppressed" and q.status == "suppressed"


def test_router_cannot_authorize_phrase_outside_whitelist(desk):
    # the router cannot name words: text always comes from a whitelisted template via render()
    [p] = run(rd("routine", 0.99), make_parsed(altitude_ft=500), desk)
    assert p.template_id in {
        "ACK_CHECKIN",
        "TRAFFIC",
        "CORRIDOR_ENTRY",
        "REPORT_ACK",
        "SAY_AGAIN",
        "STANDBY_HANDOFF",
    }


def test_agent_without_router_unchanged(desk):
    [p] = VoiceAgent(model_call).handle_transmission(make_parsed(altitude_ft=500), desk, 1000)
    assert p.tier == "auto" and p.router is None


@pytest.mark.parametrize(
    ("resp", "cause"),
    [
        (poster((403, {})), "provider unavailable"),  # service/account failure
        (poster(TimeoutError("t")), "timeout"),  # service failure
        (poster((500, None)), "HTTP 500"),  # service failure
        (poster((200, {"answers": []})), "refused or omitted"),  # missing evidence
        (poster(decisions_response("banana")), "malformed"),  # model error
        (poster(decisions_response("unknown", 0.9)), "unknown"),  # model cannot classify
    ],
)
def test_failure_causes_are_distinct_and_all_abstain_to_approval(resp, cause, desk):
    d = DecisionsRouter(api_key="k", post=resp, cache=False).route(make_parsed(), desk)
    assert d.abstained and cause in d.reason
    assert combine("auto", d)[0] == "approval"


def test_shadow_mode_records_but_never_changes_tier(desk, monkeypatch):
    monkeypatch.setenv("LANDED_ROUTER_MODE", "shadow")
    [p] = run(rd("needs_review", 0.9, attention=0.8), make_parsed(altitude_ft=500), desk)
    assert p.tier == "auto" and p.router["label"] == "needs_review" and p.router["mode"] == "shadow"


def test_shadow_is_the_default(monkeypatch):
    monkeypatch.delenv("LANDED_ROUTER_MODE", raising=False)
    assert router_mode() == "shadow"
