"""Evaluate a scenario's geometry/engine events against its generated tracks.

Each event yields geometry ``checks`` (judged locally, no server needed) and, for events that should raise
something with the voice agent, an ``alert`` payload to POST to /alerts whose answer is scored against the
event's ``response`` expectation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import scn_checks
import scn_engine
import scn_geo
import scn_tracks
from scn_model import Event, Scenario
from scoring import Check

SEV_RANK = {"advisory": 1, "caution": 2, "handoff": 3}


@dataclass
class EventEval:
    event: Event
    t: float
    checks: list[Check] = field(default_factory=list)
    alert: dict | None = None
    facts: dict = field(default_factory=dict)


def _chk(eid: str, name: str, expected, actual, ok: bool, detail: str = "") -> Check:
    return Check(f"{eid}.geometry.{name}", name, expected, actual, "pass" if ok else "fail", detail)


def episodes_for(sc: Scenario, tracks: dict) -> list[dict]:
    return scn_engine.run_engine(tracks["aircraft"], 0, sc.window_s)


def _alert_payload(ep: dict) -> dict:
    keys = (
        "id",
        "aircraft",
        "volume_id",
        "severity",
        "confidence",
        "reason",
        "time_to_entry_s",
        "entry_point",
        "entry_alt_ft",
        "first_seen_t",
        "last_seen_t",
    )
    return {k: ep[k] for k in keys}


def _logical(volume_id: str) -> str:
    vol = next(v for v in scn_geo.protected_volumes() if v["id"] == volume_id)
    return scn_engine.logical_key(vol)


def evaluate(sc: Scenario, tracks: dict, line_times: dict[str, float]) -> list[EventEval]:
    episodes = episodes_for(sc, tracks)
    out: list[EventEval] = []
    matched: set[tuple[str, str]] = set()
    for ev in sorted(sc.events, key=lambda x: x.kind != "engine_alert"):
        e = EventEval(ev, t=0.0)
        k = ev.kind
        if k == "engine_alert":
            eps = [
                p
                for p in episodes
                if p["aircraft"]["reg"] == ev.aircraft
                and p["volume_id"].startswith(ev.volume_prefix or "")
                and p["severity"] == ev.severity
            ]
            ep = eps[0] if eps else None
            e.checks.append(
                _chk(
                    ev.id,
                    "exists",
                    f"{ev.severity} {ev.volume_prefix}*",
                    ep["volume_id"] if ep else None,
                    ep is not None,
                )
            )
            if ep:
                matched.add((ev.aircraft or "", _logical(ep["volume_id"])))
                e.t = ep["t_first"]
                e.facts = {
                    "t_first": ep["t_first"],
                    "lead_s": ep["lead_s_at_first"],
                    "confidence": ep["peak_confidence"],
                    "volume_id": ep["volume_id"],
                }
                if ev.min_confidence is not None:
                    e.checks.append(
                        _chk(
                            ev.id,
                            "confidence>=",
                            ev.min_confidence,
                            ep["peak_confidence"],
                            ep["peak_confidence"] >= ev.min_confidence,
                        )
                    )
                if ev.lead_s:
                    e.checks.append(
                        _chk(
                            ev.id,
                            "lead_s",
                            list(ev.lead_s),
                            ep["lead_s_at_first"],
                            ev.lead_s[0] <= ep["lead_s_at_first"] <= ev.lead_s[1],
                        )
                    )
                if ev.t_window:
                    e.checks.append(
                        _chk(
                            ev.id,
                            "t_first",
                            list(ev.t_window),
                            ep["t_first"],
                            ev.t_window[0] <= ep["t_first"] <= ev.t_window[1],
                        )
                    )
                e.alert = _alert_payload(ep)
        elif k == "no_alerts":
            bad = [
                p
                for p in episodes
                if SEV_RANK[p["severity"]] >= SEV_RANK[ev.min_severity]
                and (ev.aircraft is None or p["aircraft"]["reg"] == ev.aircraft)
                and not any(
                    p["aircraft"]["reg"] == m[0] and _logical(p["volume_id"]) == m[1] for m in matched
                )
            ]
            e.checks.append(
                _chk(
                    ev.id,
                    f"no_alert>={ev.min_severity}",
                    "none",
                    [f"{p['aircraft']['reg']} {p['volume_id']} {p['severity']}" for p in bad] or "none",
                    not bad,
                )
            )
        elif k == "shoreline":
            hits = scn_checks.shoreline_rule(tracks, ev.aircraft or "")
            h = hits[0] if hits else None
            e.checks.append(
                _chk(ev.id, "exists", "shoreline alert", h["reason"] if h else None, h is not None)
            )
            if h:
                e.t = h["first_seen_t"]
                e.facts = h
                if ev.min_confidence is not None:
                    e.checks.append(
                        _chk(
                            ev.id,
                            "confidence>=",
                            ev.min_confidence,
                            h["confidence"],
                            h["confidence"] >= ev.min_confidence,
                        )
                    )
                if ev.t_window:
                    e.checks.append(
                        _chk(
                            ev.id,
                            "first_seen_t",
                            list(ev.t_window),
                            h["first_seen_t"],
                            ev.t_window[0] <= h["first_seen_t"] <= ev.t_window[1],
                        )
                    )
                if ev.traffic_nm:
                    nm = h["opposing_traffic"]["nm"] if h["opposing_traffic"] else None
                    e.checks.append(
                        _chk(
                            ev.id,
                            "opposing_traffic_nm",
                            list(ev.traffic_nm),
                            nm,
                            nm is not None and ev.traffic_nm[0] <= nm <= ev.traffic_nm[1],
                        )
                    )
                e.alert = {
                    "id": f"{h['reg']}:shoreline",
                    "kind": "shoreline",
                    "aircraft": {
                        "hex": next(a["hex"] for a in tracks["aircraft"] if a["reg"] == h["reg"]),
                        "reg": h["reg"],
                    },
                    "volume_id": h["volume_id"],
                    "severity": h["severity"],
                    "confidence": h["confidence"],
                    "reason": h["reason"],
                    "first_seen_t": h["first_seen_t"],
                    "last_seen_t": h["first_seen_t"],
                    "opposing_traffic": h["opposing_traffic"],
                }
        elif k == "squawk":
            hits = [s for s in scn_checks.squawk_emergency(tracks, ev.aircraft or "") if s["code"] == ev.code]
            s = hits[0] if hits else None
            e.checks.append(_chk(ev.id, "exists", ev.code, s["code"] if s else None, s is not None))
            if s:
                e.t = s["t"]
                e.facts = s
                if ev.t_window:
                    e.checks.append(
                        _chk(
                            ev.id, "t", list(ev.t_window), s["t"], ev.t_window[0] <= s["t"] <= ev.t_window[1]
                        )
                    )
                e.alert = {
                    "id": f"{ev.aircraft}:squawk{s['code']}",
                    "kind": "squawk",
                    "squawk": s["code"],
                    "aircraft": {
                        "hex": next(a["hex"] for a in tracks["aircraft"] if a["reg"] == ev.aircraft),
                        "reg": ev.aircraft,
                    },
                    "severity": "handoff",
                    "confidence": 1.0,
                    "reason": f"{ev.aircraft}: squawk {s['code']} on simulated ADS-B.",
                    "first_seen_t": s["t"],
                    "last_seen_t": s["t"],
                }
        elif k == "position_match":
            t = line_times[ev.at_line or ""]
            e.t = t
            line = next(ln for ln in sc.lines if ln.id == ev.at_line)
            pm = scn_checks.position_match(tracks, ev.reported or "", t)
            best = pm["best"]
            e.facts = pm
            e.checks.append(
                _chk(
                    ev.id,
                    "best_match",
                    line.aircraft,
                    best["reg"] if best else None,
                    bool(best) and best["reg"] == line.aircraft,
                )
            )
            e.checks.append(
                _chk(
                    ev.id,
                    "score>=",
                    ev.min_score,
                    best["score"] if best else None,
                    bool(best) and best["score"] >= ev.min_score,
                )
            )
            e.checks.append(_chk(ev.id, "unique", True, pm["unique"], pm["unique"]))
        elif k == "desk_count":
            t = ev.at_t or 0.0
            e.t = t
            dc = scn_checks.desk_count(tracks, t)
            e.facts = dc
            e.checks.append(
                _chk(ev.id, "count", ev.count, dc["count"], dc["count"] == ev.count, str(dc["regs"]))
            )
        out.append(e)

    if any(ev.kind == "engine_alert" for ev in sc.events):
        extra = [
            p
            for p in episodes
            if SEV_RANK[p["severity"]] >= SEV_RANK["caution"]
            and (p["aircraft"]["reg"], _logical(p["volume_id"])) not in matched
        ]
        ee = EventEval(Event(id="ENGINE", kind="no_alerts", min_severity="caution"), t=0.0)
        ee.checks.append(
            _chk(
                "ENGINE",
                "no_unexpected_alert",
                "none",
                [f"{p['aircraft']['reg']} {p['volume_id']} {p['severity']}" for p in extra] or "none",
                not extra,
            )
        )
        out.append(ee)
    return out


def aircraft_context(tracks: dict, t: float) -> list[dict]:
    ctx = []
    for a in tracks["aircraft"]:
        p = scn_tracks.position_at(a, t)
        if p is None:
            continue
        ctx.append(
            {
                "reg": a["reg"],
                "hex": a["hex"],
                "lat": round(p[0], 5),
                "lon": round(p[1], 5),
                "alt_ft": round(p[2]),
                "squawk": scn_tracks.squawk_at(a, t),
                "desk": a.get("desk", True),
            }
        )
    return ctx
