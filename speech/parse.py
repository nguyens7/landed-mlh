"""Transmission parser: deterministic grammar first, LLM structured-output fallback.

Confidence is computed from evidence, never assigned per outcome:
  parse_confidence = intent_strength * (FLOOR + (1 - FLOOR) * coverage) * callsign_factor
  * intent_strength: share of the intent's cue patterns that fired (saturating)
  * coverage: fraction of words explained by a recognised pattern (callsign, place, number, cue, filler)
  * callsign_factor: snap score (halved if ambiguous); fixed penalty floors when absent/unsnapped
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import threading
from pathlib import Path

from models import Callsign, Intent, ParsedTransmission, Slots
from normalize import MULTIPLIERS, TEENS, TENS, group_runs, is_letter_token, lex, spell_callsign
from places import position_id_for
from snap import load_roster, snap

CACHE_DIR = Path(__file__).parent / ".cache" / "llm_gemini"
LLM_MODEL = "gemini-3.5-flash-lite"
LLM_TRIGGER = 0.5          # below this grammar parse_confidence -> consult the LLM
COVERAGE_FLOOR = 0.4
NO_CALLSIGN_FACTOR = 0.3
UNSNAPPED_CALLSIGN_FACTOR = 0.4

# ----------------------------------------------------------------------------- gazetteer
PLACES: list[tuple[str, str]] = [
    ("Downtown Skyport", r"downtown (?:skyport|manhattan heliport|heliport)|\bjrb\b|\bskyport\b"),
    ("East 34th", r"east (?:34|thirty ?four)(?:th|st)?(?: street)?(?: heliport)?|34th street(?: heliport)?|\b6n5\b"),
    ("Brooklyn Bridge", r"brooklyn bridge"),
    ("Manhattan Bridge", r"manhattan bridge"),
    ("Williamsburg Bridge", r"williamsburg bridge"),
    ("Queensboro Bridge", r"queensboro bridge|59th street bridge|fifty ninth street bridge"),
    ("Roosevelt Island", r"roosevelt island"),
    ("Intrepid", r"\bintrepid\b"),
    ("Statue of Liberty", r"statue of liberty|\bliberty island\b"),
    ("George Washington Bridge", r"george washington(?: bridge)?|\bgw bridge\b"),
    ("Hell Gate", r"hell ?gate"),
    ("Governors Island", r"governors island"),
    ("LaGuardia", r"la ?guardia|\blga\b"),
    ("Flushing Hospital", r"flushing hospital(?: area)?"),
    ("College Point", r"college point(?: area)?"),
    ("Bellevue", r"\bbellevue\b"),
    ("NYU Langone", r"nyu langone|\blangone\b"),
    ("Battery", r"\bthe battery\b|\bbattery\b"),
]
PLACE_RES = [(name, re.compile(pat)) for name, pat in PLACES]

CORRIDORS = [("Hudson", re.compile(r"\bhudson\b")), ("East River", re.compile(r"\beast river\b"))]
DIRECTION_RE = re.compile(r"\b(north|south|east|west)\s?bound\b")

WEATHER = [
    ("inadvertent imc", re.compile(r"inadvertent imc|inadvertent instrument")),
    ("ceilings coming down", re.compile(r"ceilings?(?: is| are)? (?:coming|going|dropping|lowering)(?: down)?|low ceilings?")),
    ("losing visual", re.compile(r"(?:losing|lost|lose) (?:visual|visuals|the visual|visibility|ground contact)")),
    ("special vfr", re.compile(r"special vfr|\bsvfr\b")),
    ("visibility dropping", re.compile(r"visibility (?:is )?(?:dropping|decreasing|reducing|deteriorating)")),
    ("imc", re.compile(r"\bimc\b")),
    ("fog", re.compile(r"\bfog\b")),
]

EMERGENCY_RE = re.compile(r"\bmayday\b|\bpan ?pan\b|\bemergency\b")
STRONG_EMERGENCY_RE = re.compile(r"\bmayday\b|\bpan ?pan\b")
EMERGENCY_SQUAWKS = {"7700", "7600", "7500"}

ORIGIN_AFTER = re.compile(r"^\s*(?:,?\s*)(?:lifting|lifted|departing|airborne|taking off|takeoff|lift off|liftoff|departure)\b")
ORIGIN_BEFORE = re.compile(r"\bfrom\s+(?:the\s+)?$")
DEST_BEFORE = re.compile(r"\b(?:landing|land|to|toward|towards|inbound|direct|via|transit|transiting|cross|crossing|destination|proceeding)\s+(?:the\s+|at\s+)?$")
POS_BEFORE = re.compile(r"\b(?:abeam|over|passing|approaching|reaching|off|near|at|by|report|reporting|overhead|remain east of|remain west of|east of|west of)\s+(?:the\s+)?$")

INTENT_CUES: dict[str, list[re.Pattern]] = {
    "readback": [re.compile(p) for p in (
        r"\broger\b", r"\bwilco\b", r"\bcopy\b", r"\bwill report\b", r"\bwill call\b",
        r"^(?:report|remain|maintain|stay|hold|enter|proceed|expect)\b", r"\bat or below\b")],
    "request": [re.compile(p) for p in (r"\brequest(?:ing)?\b", r"\bwould like\b", r"\bneed\b")],
    "checkin": [re.compile(p) for p in (
        r"\blift(?:ing|ed)\b", r"\bliftoff\b|\blift off\b", r"\bdeparting\b", r"\bairborne\b",
        r"\btaking off\b|\btakeoff\b", r"\bchecking in\b|\bcheck in\b", r"\bwith you\b")],
    "position_report": [re.compile(p) for p in (
        r"\babeam\b", r"\bover\b", r"\bpassing\b", r"\bapproaching\b", r"\boverhead\b", r"\breaching\b",
        r"\blanding\b")],
}
ROUTE_CUES = re.compile(r"\b(?:direct|route|routing|transit|cross|crossing|via|proceed|deviate|divert|detour)\b")
ALT_CUES = re.compile(r"\b(?:descend|descent|climb|altitude|lower|higher|level)\b")
FILLER = set("""landed desk new york helo uh um er the a an and at to of for on in with this is you your
 how do hear radio check say again last station position request requesting like would feet ft msl bound
 my we our i it is are now just please sir thanks thank over out medevac""".split())


# A street number is an ordinal ("34th", "34th Street") or a number after a direction ("East 34", "East thirty four").
# Those digits belong to a place name, so they are masked to a non-numeric word before lexing; otherwise the
# lexer's digit run would merge "East 34th 500" into 34500.
STREET_NUMBER_RE = re.compile(
    r"\b\d+(?:st|nd|rd|th)\b"
    r"|\b(?:east|west|north|south)\s+(?:\d{1,3}|thirty[\s-]?four)(?:st|nd|rd|th)?\b"
    r"|\bthirty[\s-]?fourth\b",
    re.IGNORECASE,
)


def mask_street_numbers(text: str) -> str:
    """Replace street-number phrases with the word 'ordinal' so they never join an altitude run."""
    return STREET_NUMBER_RE.sub(" ordinal ", text.replace("’", "'"))


def prep(text: str) -> str:
    """Plain lower-case text for pattern matching (hyphens/punct to spaces, commas kept)."""
    s = text.lower().replace("’", "'")
    s = re.sub(r"(?<=[a-z])'(?=[a-z])", "", s)  # ceiling's -> ceilings, before punctuation is blanked
    s = re.sub(r"x[\s-]?ray", "xray", s)
    s = re.sub(r"\bi\.?\s?m\.?\s?c\b", "imc", s)
    s = re.sub(r"\bv\.?\s?f\.?\s?r\b", "vfr", s)
    s = re.sub(r"\bpan[\s-]+pan\b", "panpan", s)
    s = re.sub(r"\bmay[\s-]+day\b", "mayday", s)
    s = re.sub(r"[^a-z0-9, ]", " ", s)
    return re.sub(r"[ ]+", " ", s).strip()


# ----------------------------------------------------------------------------- callsign
def extract_callsign(tokens: list[str]) -> tuple[str | None, str | None, tuple[int, int] | None]:
    """Return (normalized, spoken, token_span) from lexed tokens."""
    n = len(tokens)

    def collect(i: int, lead_n: bool) -> tuple[str, int] | None:
        digits = ""
        j = i
        while j < n and tokens[j].isdigit() and len(digits) < 5:
            if j + 1 < n and tokens[j + 1] in MULTIPLIERS:
                break
            digits += tokens[j]
            j += 1
        letters = ""
        while j < n and is_letter_token(tokens[j]) and len(letters) < 2:
            letters += tokens[j]
            j += 1
        if not digits:
            return None
        return ("N" if lead_n else "") + digits + letters, j

    # 1) after "medevac"
    for i, t in enumerate(tokens):
        if t == "medevac":
            k = i + 1
            lead_n = False
            if k + 1 < n and tokens[k] == "N" and tokens[k + 1].isdigit():
                lead_n, k = True, k + 1
            got = collect(k, lead_n)
            if got:
                norm, end = got
                return norm, _spoken(norm), (i + 1, end)
    # 2) November-prefixed tail number anywhere
    for i, t in enumerate(tokens):
        if t == "N" and i + 1 < n and tokens[i + 1].isdigit():
            got = collect(i + 1, True)
            if got:
                norm, end = got
                return norm, _spoken(norm), (i, end)
    # 3) bare digit string at the start of the utterance
    start = 0
    while start < n and not tokens[start].isdigit():
        if tokens[start] not in FILLER and tokens[start] != ",":
            return None, None, None
        start += 1
    if start < n:
        got = collect(start, False)
        if got and len(got[0]) >= 3:
            return got[0], _spoken(got[0]), (start, got[1])
    return None, None, None


def _spoken(norm: str) -> str:
    return spell_callsign(norm)


# ----------------------------------------------------------------------------- altitude / squawk
def extract_altitude(tokens: list[str], skip: tuple[int, int] | None, squawk_span: tuple[int, int] | None) -> int | None:
    from normalize import collapse_run

    found: list[int] = []
    pos = 0
    for kind, toks in group_runs(tokens):
        start, end = pos, pos + len(toks)
        pos = end
        if kind != "run":
            continue
        # drop the callsign span / squawk span and any leading callsign letters from the run
        idx = list(range(start, end))
        idx = [i for i in idx if not (skip and skip[0] <= i < skip[1]) and not (squawk_span and squawk_span[0] <= i < squawk_span[1])]
        run = [tokens[i] for i in idx]
        # numeric segment after the last letter
        while run and is_letter_token(run[0]):
            run = run[1:]
        if any(is_letter_token(t) for t in run):
            last = max(k for k, t in enumerate(run) if is_letter_token(t))
            run = run[last + 1:]
        if not run:
            continue
        if any(t in MULTIPLIERS for t in run):
            val = int(collapse_run(run))
            if 100 <= val <= 18000:
                found.append(val)
        else:
            # ASR often writes altitudes as digits ("1500"): accept a standalone 3-5 digit round number
            # that is not the callsign or squawk (both were removed from the run above).
            digits = collapse_run(run)
            if 3 <= len(digits) <= 5 and digits.isdigit() and int(digits) % 100 == 0:
                found.append(int(digits))
    return found[-1] if found else None


def extract_squawk(tokens: list[str]) -> tuple[str | None, tuple[int, int] | None]:
    for i, t in enumerate(tokens):
        if t in {"squawk", "transponder", "code"}:
            j, digits = i + 1, ""
            while j < len(tokens) and tokens[j].isdigit() and len(digits) < 4:
                digits += tokens[j]
                j += 1
            if len(digits) == 4:
                return digits, (i + 1, j)
    return None, None


# ----------------------------------------------------------------------------- grammar parser
def _find_places(plain: str) -> list[tuple[str, int, int]]:
    hits: list[tuple[str, int, int]] = []
    for name, rx in PLACE_RES:
        for m in rx.finditer(plain):
            hits.append((name, m.start(), m.end()))
    hits.sort(key=lambda h: (h[1], -(h[2] - h[1])))
    out: list[tuple[str, int, int]] = []
    last_end = -1
    for h in hits:
        if h[1] >= last_end:
            out.append(h)
            last_end = h[2]
    return out


def _clause_before(plain: str, start: int) -> str:
    left = plain[:start]
    return left[left.rfind(",") + 1:] if "," in left else left


def grammar_parse(text: str) -> tuple[ParsedTransmission, dict]:
    """Deterministic parse. Returns the (callsign-unsnapped) result and diagnostics."""
    tokens = lex(mask_street_numbers(text))
    plain = prep(text)
    norm, spoken, span = extract_callsign(tokens)
    squawk, squawk_span = extract_squawk(tokens)
    altitude = extract_altitude(tokens, span, squawk_span)

    spans: list[tuple[int, int]] = []      # explained char spans in plain text

    # places and roles
    places = _find_places(plain)
    roles: dict[str, str | None] = {"position": None, "origin": None, "destination": None}
    unassigned: list[str] = []
    for name, s, e in places:
        spans.append((s, e))
        before = _clause_before(plain, s)
        if ORIGIN_AFTER.match(plain[e:]) or ORIGIN_BEFORE.search(before):
            role = "origin"
        elif DEST_BEFORE.search(before):
            role = "destination"
        elif POS_BEFORE.search(before):
            role = "position"
        else:
            role = None
        if role and roles[role] is None:
            roles[role] = name
        elif role is None:
            unassigned.append(name)

    corridor = next((n for n, rx in CORRIDORS if rx.search(plain)), None)
    for _, rx in CORRIDORS:
        spans.extend(m.span() for m in rx.finditer(plain))
    dm = DIRECTION_RE.search(plain)
    direction = f"{dm.group(1)}bound" if dm else None
    spans.extend(m.span() for m in DIRECTION_RE.finditer(plain))

    weather = None
    for name, rx in WEATHER:
        m = rx.search(plain)
        if m:
            weather = name
            spans.append(m.span())
            break

    # intent
    emergency = bool(EMERGENCY_RE.search(plain)) or (squawk in EMERGENCY_SQUAWKS)
    strong_emergency = bool(STRONG_EMERGENCY_RE.search(plain)) or (squawk in EMERGENCY_SQUAWKS)
    for rx in [STRONG_EMERGENCY_RE, EMERGENCY_RE]:
        spans.extend(m.span() for m in rx.finditer(plain))
    body = re.sub(r"^(?:(?:landed|new york|helo) desk|uh|um|,|\s)+", "", plain)
    cue_hits: dict[str, int] = {}
    cue_words: dict[str, list[str]] = {}
    for intent, rxs in INTENT_CUES.items():
        hits = 0
        cue_words[intent] = []
        for rx in rxs:
            for m in rx.finditer(plain if not rx.pattern.startswith("^") else body):
                hits += 1
                cue_words[intent].append(m.group(0))
                if not rx.pattern.startswith("^"):
                    spans.append(m.span())
                else:
                    spans.append((plain.find(m.group(0)), plain.find(m.group(0)) + len(m.group(0))))
        cue_hits[intent] = hits
    for rx in (ROUTE_CUES, ALT_CUES):
        spans.extend(m.span() for m in rx.finditer(plain))

    intent: Intent = "unknown"
    strength = 0.0
    if emergency:
        intent = "emergency"
        strength = 1.0 if strong_emergency else 0.7
    elif cue_hits["request"]:
        if ROUTE_CUES.search(plain) or (not ALT_CUES.search(plain) and (places or altitude)):
            intent = "request_route"
        elif ALT_CUES.search(plain):
            intent = "request_altitude"
        n_extra = 1 if (ROUTE_CUES.search(plain) or ALT_CUES.search(plain)) else 0
        strength = min(1.0, 0.5 + 0.25 * (cue_hits["request"] + n_extra))
        if intent == "unknown":
            strength = 0.0
    elif cue_hits["readback"] and not cue_hits["checkin"]:
        intent = "readback"
        strength = min(1.0, 0.5 * cue_hits["readback"] + 0.25)
    elif cue_hits["checkin"]:
        intent = "checkin"
        strength = min(1.0, 0.5 * cue_hits["checkin"] + 0.25 * bool(places))
    elif cue_hits["position_report"] or roles["position"] or ((places or altitude or direction or corridor) and norm):
        intent = "position_report"
        n = cue_hits["position_report"] + bool(roles["position"] or roles["destination"])
        strength = min(1.0, 0.35 + 0.2 * n + 0.1 * bool(altitude))
    # radio-check style transmissions stay unknown
    if intent == "unknown" and re.search(r"radio check|say again|how do you hear|standby|stand by", plain):
        strength = 0.0

    # slot assembly
    position = roles["position"]
    origin = roles["origin"]
    destination = roles["destination"]
    if intent == "checkin" and position is None:
        position = origin or (unassigned[0] if unassigned else None)
    if intent in {"request_route", "request_altitude", "position_report"} and position is None and unassigned:
        before_req = plain.find("request")
        first = next(((n_, s_) for n_, s_, _ in places if n_ in unassigned), None)
        if first and (before_req < 0 or first[1] < before_req):
            position = first[0]
    if intent == "position_report" and position is None and unassigned and destination is None:
        position = unassigned[0]

    slots = Slots(position=position, position_id=position_id_for(position), altitude_ft=altitude,
                  direction=direction, corridor=corridor,
                  origin=origin, destination=destination, weather_phrase=weather, squawk=squawk)

    # coverage
    words = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[a-z0-9]+", plain)]
    explained = 0
    numeric_words = set("zero one two three four five six seven eight nine niner tree fife fower hundred thousand".split()) | set(TEENS) | set(TENS)
    from normalize import PHONETIC
    for w, s, e in words:
        if (w in FILLER or w in numeric_words or w in PHONETIC or w.isdigit() or len(w) == 1
                or any(a <= s and e <= b for a, b in spans)):
            explained += 1
    coverage = explained / len(words) if words else 0.0

    pt = ParsedTransmission(
        raw_text=text,
        callsign=Callsign(spoken=spoken, normalized=norm),
        intent=intent, slots=slots, emergency=emergency, parser="grammar",
    )
    diag = {"strength": strength, "coverage": coverage, "cues": cue_words.get(
        {"request_route": "request", "request_altitude": "request"}.get(intent, intent), [])}
    return pt, diag


@functools.lru_cache(maxsize=1)
def _default_roster() -> tuple[str, ...]:
    return tuple(load_roster())


def _apply_snap(pt: ParsedTransmission, roster: list[str]) -> None:
    res = snap(pt.callsign.normalized, roster)
    pt.callsign.snapped_to = res.snapped_to
    pt.callsign.snap_score = res.snap_score
    pt.callsign.ambiguous_with = res.ambiguous_with


def _callsign_factor(pt: ParsedTransmission) -> float:
    if not pt.callsign.normalized:
        return NO_CALLSIGN_FACTOR
    if not pt.callsign.snapped_to:
        return UNSNAPPED_CALLSIGN_FACTOR
    f = pt.callsign.snap_score
    return f * 0.5 if pt.callsign.ambiguous_with else f


def _score(pt: ParsedTransmission, diag: dict) -> float:
    return max(0.0, min(1.0, diag["strength"] * (COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * diag["coverage"]) * _callsign_factor(pt)))


def explain(pt: ParsedTransmission, cues: list[str] | None = None) -> str:
    """Human-readable reason string for an approval card or audit log."""
    c, parts = pt.callsign, []
    if c.snapped_to:
        s = f"Callsign heard as '{c.spoken}' ({c.normalized}) snapped to {c.snapped_to} (score {c.snap_score:.2f})"
        if c.ambiguous_with:
            s += f", but also close to {', '.join(c.ambiguous_with)}: do not guess, confirm by voice or ADS-B"
        parts.append(s)
    elif c.normalized:
        parts.append(f"Callsign '{c.normalized}' matches no roster aircraft")
    else:
        parts.append("No callsign heard")
    why = f" (cues: {', '.join(sorted(set(cues)))})" if cues else ""
    parts.append(f"intent {pt.intent}{why}")
    filled = {k: v for k, v in pt.slots.model_dump().items() if v is not None}
    parts.append("slots " + (", ".join(f"{k}={v}" for k, v in filled.items()) if filled else "none"))
    if pt.emergency:
        parts.append("EMERGENCY keyword or squawk present")
    ac = "n/a" if pt.asr_confidence is None else f"{pt.asr_confidence:.2f}"
    parts.append(f"ASR confidence {ac}, parse confidence {pt.parse_confidence:.2f} ({pt.parser} parser)")
    return "; ".join(parts) + "."


def parse_transmission(text: str, asr_confidence: float | None = None, roster: list[str] | None = None,
                       llm: bool = True) -> ParsedTransmission:
    pt = _parse(text, asr_confidence, roster, llm)
    return pt


def _parse(text: str, asr_confidence: float | None, roster: list[str] | None, llm: bool) -> ParsedTransmission:
    roster = roster if roster is not None else list(_default_roster())
    _tl.llm_latency = None
    pt, diag = grammar_parse(text)
    pt.asr_confidence = asr_confidence
    _apply_snap(pt, roster)
    pt.parse_confidence = round(_score(pt, diag), 4)
    pt.reason = explain(pt, diag["cues"])
    # Consult the LLM when the grammar itself is unsure (callsign ambiguity is not a grammar failure).
    grammar_quality = diag["strength"] * (COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * diag["coverage"])
    if llm and (pt.intent == "unknown" or grammar_quality < LLM_TRIGGER):
        alt = llm_parse(text, roster, pt, diag["coverage"])
        if alt is not None:
            alt.asr_confidence = asr_confidence
            alt.reason = explain(alt) + " Grammar was unsure; LLM output kept only values found in the text."
            if alt.parse_confidence > pt.parse_confidence:
                return alt
    return pt


# ----------------------------------------------------------------------------- LLM fallback
LLM_SYSTEM = """You convert one helicopter radio transmission (NYC medevac desk) into JSON.
Rules: extract only what was said. If a field is not stated or you are unsure, use null. Never guess or
repair garbled words; a partial callsign stays partial. Digits: 'niner'=9, 'one thousand five hundred'=1500.
callsign_normalized: digits then letters, e.g. 'Four Five Alpha Bravo' -> '45AB'; 'November Seven Eight Zero Charlie' -> 'N780C'. Keep a truncated callsign truncated.
intent: checkin (lifting/departing/checking in), position_report (abeam/over/passing a place or status), request_route,
request_altitude, readback (roger/wilco/repeating an instruction), emergency (MAYDAY/PAN-PAN/7700), unknown (radio check, unclear).
Places must be one of: """ + ", ".join(n for n, _ in PLACES) + """; otherwise null.
corridor is 'Hudson' or 'East River' only. direction like 'northbound'. weather_phrase: short phrase as said (e.g. 'ceilings coming down', 'inadvertent IMC').
squawk is a 4-digit string."""


def _llm_schema():
    from pydantic import BaseModel

    class LlmSlots(BaseModel):
        position: str | None
        altitude_ft: int | None
        direction: str | None
        corridor: str | None
        origin: str | None
        destination: str | None
        weather_phrase: str | None
        squawk: str | None

    class LlmParse(BaseModel):
        callsign_normalized: str | None
        intent: Intent
        slots: LlmSlots
        emergency: bool

    return LlmParse


def _canon_place(v: str | None) -> str | None:
    if not v:
        return None
    p = prep(v)
    for name, rx in PLACE_RES:
        if rx.search(p) or name.lower() == p:
            return name
    return None


def _canon_weather(v: str | None) -> str | None:
    if not v:
        return None
    p = prep(v)
    for name, rx in WEATHER:
        if rx.search(p):
            return name
    return None


_tl = threading.local()


def last_llm_latency() -> float | None:
    """Latency (s) of the most recent LLM call made by this thread's parse, or None if none was made."""
    return getattr(_tl, "llm_latency", None)


def llm_raw(text: str) -> dict:
    raw = _llm_raw_inner(text)
    _tl.llm_latency = raw["latency_s"]
    return raw


def _llm_raw_inner(text: str) -> dict:
    """Call Gemini generateContent with a response schema. Returns {data, latency_s, valid}.

    ``valid`` is True only when the first response is complete (finish STOP), parseable JSON and passes
    the Pydantic schema. API/transport errors are retried; invalid content is not (it counts against the gate).
    """
    key = hashlib.sha256(f"{LLM_MODEL}|{LLM_SYSTEM}|{text}".encode()).hexdigest()
    cache = CACHE_DIR / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    import time

    from google.genai import types

    from keys import gemini_client
    client = gemini_client()
    LlmParse = _llm_schema()
    cfg = types.GenerateContentConfig(
        system_instruction=LLM_SYSTEM, temperature=0, response_mime_type="application/json",
        response_schema=LlmParse, max_output_tokens=2000,
        thinking_config=types.ThinkingConfig(thinking_level="minimal"))
    last: Exception | None = None
    for attempt in range(4):
        try:
            t0 = time.time()
            r = client.models.generate_content(model=LLM_MODEL, contents=text, config=cfg)
            latency = time.time() - t0
            break
        except Exception as e:  # noqa: BLE001 - transport/rate-limit errors are retried
            last = e
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"Gemini parse call failed: {last}")
    valid, data = True, None
    try:
        if str(r.candidates[0].finish_reason) not in ("FinishReason.STOP", "STOP"):
            raise ValueError("incomplete")
        data = LlmParse.model_validate_json(r.text).model_dump()
    except Exception:  # noqa: BLE001 - any invalid output is recorded, not hidden
        valid = False
    out = {"data": data, "latency_s": latency, "valid": valid}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def llm_parse(text: str, roster: list[str], grammar_pt: ParsedTransmission | None = None,
              coverage: float = 1.0) -> ParsedTransmission | None:
    raw = llm_raw(text)
    data = raw["data"]
    if not raw["valid"] or data is None:
        return None

    tokens = lex(mask_street_numbers(text))
    norm = data.get("callsign_normalized")
    norm = re.sub(r"[^A-Z0-9]", "", norm.upper()) if norm else None
    s = data["slots"]
    slots = Slots(
        position=_canon_place(s.get("position")), altitude_ft=s.get("altitude_ft"),
        direction=(s.get("direction") or "").lower() or None,
        corridor=s.get("corridor") if s.get("corridor") in {"Hudson", "East River"} else None,
        origin=_canon_place(s.get("origin")), destination=_canon_place(s.get("destination")),
        weather_phrase=_canon_weather(s.get("weather_phrase")),
        squawk=s.get("squawk") if s.get("squawk") and re.fullmatch(r"\d{4}", s["squawk"]) else None,
    )
    pt = ParsedTransmission(
        raw_text=text, callsign=Callsign(spoken=spell_callsign(norm) if norm else None, normalized=norm),
        intent=data["intent"], slots=slots,
        emergency=bool(data["emergency"]) or slots.squawk in EMERGENCY_SQUAWKS, parser="llm")
    _apply_snap(pt, roster)

    # Grounding: every extracted value must be recoverable from the text (no invention).
    # Ungrounded values are dropped to null (the opposite of "make an educated guess") and
    # reduce the confidence.
    plain = prep(text)
    place_hits = {n for n, _, _ in _find_places(plain)}
    checks: list[bool] = []

    def ground(value, ok: bool):
        checks.append(ok)
        return value if ok else None

    if norm:
        spoken_alnum = "".join(t if t.isdigit() or is_letter_token(t) else "" for t in tokens)
        if not ground(norm, core_in(norm, spoken_alnum)):
            norm = None
            pt.callsign = Callsign()
            _apply_snap(pt, roster)
    sl = pt.slots
    if sl.altitude_ft is not None:
        sl.altitude_ft = ground(sl.altitude_ft, sl.altitude_ft in _all_numbers(tokens))
    for f in ("position", "origin", "destination"):
        v = getattr(sl, f)
        if v:
            setattr(sl, f, ground(v, v in place_hits))
    sl.position_id = position_id_for(sl.position)
    if sl.corridor:
        sl.corridor = ground(sl.corridor, any(n == sl.corridor and rx.search(plain) for n, rx in CORRIDORS))
    if sl.direction:
        dm = DIRECTION_RE.search(plain)
        sl.direction = ground(sl.direction, bool(dm) and sl.direction == f"{dm.group(1)}bound")
    if sl.weather_phrase:
        sl.weather_phrase = ground(sl.weather_phrase, any(n == sl.weather_phrase and rx.search(plain) for n, rx in WEATHER))
    if sl.squawk:
        sl.squawk = ground(sl.squawk, sl.squawk == extract_squawk(tokens)[0])
    grounding = sum(checks) / len(checks) if checks else 0.5
    agreement = 1.0
    if grammar_pt is not None:
        pairs = [(grammar_pt.callsign.normalized, pt.callsign.normalized),
                 (grammar_pt.slots.altitude_ft, pt.slots.altitude_ft),
                 (grammar_pt.slots.corridor, pt.slots.corridor), (grammar_pt.slots.direction, pt.slots.direction)]
        known = [(a, b) for a, b in pairs if a is not None]
        agreement = sum(a == b for a, b in known) / len(known) if known else 1.0
    intent_ok = 0.0 if pt.intent == "unknown" else 1.0
    cov = COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * coverage
    pt.parse_confidence = round(max(0.0, min(1.0, intent_ok * grounding * (0.5 + 0.5 * agreement) * cov
                                             * _callsign_factor(pt))), 4)
    pt.reason = explain(pt) + " Parsed by LLM structured output; values not found in the text were dropped."
    return pt


def core_in(norm: str, spoken_alnum: str) -> bool:
    n = norm[1:] if norm.startswith("N") and len(norm) > 1 and norm[1].isdigit() else norm
    return n in spoken_alnum


def _all_numbers(tokens: list[str]) -> set[int]:
    from normalize import collapse_run

    out: set[int] = set()
    for kind, toks in group_runs(tokens):
        if kind == "run":
            nums = [t for t in toks if not is_letter_token(t)]
            if nums:
                try:
                    out.add(int(collapse_run(nums)))
                except ValueError:
                    pass
    return out


if __name__ == "__main__":
    import sys

    print(parse_transmission(" ".join(sys.argv[1:]), llm=False).model_dump_json(indent=2))
