"""Python port of the app's conflict engine (app/src/engine/*.ts) so scenarios can be scored headless.

This mirrors ``ConflictEngine.tick`` (projected-volume handoffs, near-miss caution/advisory, Class B floor)
including the least-squares vertical-rate estimator, the confidence formula and the 12 s hysteresis. The
TypeScript engine stays the source of truth; ``tests/test_engine_parity.py`` pins the S2 numbers (alert time
and lead) that the app produces for the same track so drift shows up as a test failure.

``snapshots_at`` reproduces ``app/src/data/interpolate.ts`` (linear interpolation of replay points).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# isort: split
from landed_geo import dest_point, great_circle_dist_nm

import scn_geo

PROJECTION_HORIZON_S = 90
PROJECTION_STEP_S = 3
NEAR_MISS_NM = 0.3
ADVISORY_NM = 1.0
HYSTERESIS_S = 12
CLASS_B_MARGIN_FT = 100
DEPTH_REFERENCE_NM = 1.0
CLASS_B_ALT_REFERENCE_FT = 300
STABILITY_REFERENCE_DEG = 60
FRESHNESS_REFERENCE_S = 10
VR_WINDOW_S = 25
VR_MIN_SAMPLES = 3
VR_MIN_SPAN_S = 8
VR_MAX_FPM = 1500
VR_DEADBAND_FPM = 200


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class Snapshot:
    hex: str
    reg: str
    t: float
    lat: float
    lon: float
    alt_ft: float
    gs_kt: float
    track_deg: float
    climb_fpm: float = 0.0
    track_history: list[float] = field(default_factory=list)
    data_age_s: float = 0.0


@dataclass
class Alert:
    id: str
    hex: str
    reg: str
    volume_id: str
    severity: str
    confidence: float
    reason: str
    time_to_entry_s: float
    entry_lat: float
    entry_lon: float
    entry_alt_ft: float
    first_seen_t: float
    last_seen_t: float
    _last_real_tick: float = 0.0
    also_volumes: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "id": self.id,
            "aircraft": {"hex": self.hex, "reg": self.reg},
            "volume_id": self.volume_id,
            "severity": self.severity,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "time_to_entry_s": self.time_to_entry_s,
            "entry_point": {"lat": self.entry_lat, "lon": self.entry_lon},
            "entry_alt_ft": round(self.entry_alt_ft, 1),
            "first_seen_t": self.first_seen_t,
            "last_seen_t": self.last_seen_t,
            "also_volumes": list(self.also_volumes),
        }


# ------------------------------------------------------------------ interpolation (data/interpolate.ts)
def _interp_heading(a: float, b: float, frac: float) -> float:
    diff = ((b - a + 540) % 360) - 180
    return (a + diff * frac + 360) % 360


def interpolate(ac: dict, t: float) -> Snapshot | None:
    pts = ac["points"]
    if not pts or t < pts[0]["t"] or t > pts[-1]["t"]:
        return None
    lo, hi = 0, len(pts) - 1
    while hi - lo > 1:
        mid = (lo + hi) >> 1
        if pts[mid]["t"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = pts[lo], pts[hi]
    span = b["t"] - a["t"]
    frac = (t - a["t"]) / span if span > 0 else 0.0
    climb = ((b["alt_ft_msl"] - a["alt_ft_msl"]) / span) * 60 if span > 0 else 0.0
    hist = [p["track_deg"] for p in pts[max(0, lo - 4) : lo + 1]]
    return Snapshot(
        hex=ac["hex"],
        reg=ac["reg"],
        t=t,
        lat=a["lat"] + (b["lat"] - a["lat"]) * frac,
        lon=a["lon"] + (b["lon"] - a["lon"]) * frac,
        alt_ft=a["alt_ft_msl"] + (b["alt_ft_msl"] - a["alt_ft_msl"]) * frac,
        gs_kt=a["gs_kt"] + (b["gs_kt"] - a["gs_kt"]) * frac,
        track_deg=_interp_heading(a["track_deg"], b["track_deg"], frac),
        climb_fpm=climb,
        track_history=hist,
        data_age_s=min(span, t - a["t"]),
    )


# ------------------------------------------------------------------ vertical rate (verticalRate.ts)
def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[(n - 1) // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def fit_vertical_rate(samples: list[tuple[float, float]], now: float) -> tuple[float, float]:
    """Returns (rate_fpm, smoothed_alt_ft) for samples [(t, alt)]."""
    pts = [s for s in samples if now - VR_WINDOW_S <= s[0] <= now]
    if not pts:
        return 0.0, math.nan
    latest = max(pts, key=lambda p: p[0])
    t_min, t_max = min(p[0] for p in pts), max(p[0] for p in pts)
    if len(pts) < VR_MIN_SAMPLES or t_max - t_min < VR_MIN_SPAN_S:
        return 0.0, latest[1]
    n = len(pts)
    mean_t = sum(p[0] for p in pts) / n
    mean_a = sum(p[1] for p in pts) / n
    med_a, med_t = _median([p[1] for p in pts]), _median([p[0] for p in pts])
    sxx = sum((p[0] - mean_t) ** 2 for p in pts)
    sxy = sum((p[0] - mean_t) * (p[1] - mean_a) for p in pts)
    slope = sxy / sxx if sxx > 0 else 0.0
    raw = slope * 60
    clamped = max(-VR_MAX_FPM, min(VR_MAX_FPM, raw))
    rate = 0.0 if abs(clamped) < VR_DEADBAND_FPM else clamped
    return rate, med_a + slope * (now - med_t)


# ------------------------------------------------------------------ geometry / projection
def heading_std_dev(headings: list[float]) -> float:
    if len(headings) < 2:
        return 180.0  # one heading is no evidence of a steady track (engine MAX_HEADING_STDDEV_DEG)
    ms = sum(math.sin(math.radians(h)) for h in headings) / len(headings)
    mc = sum(math.cos(math.radians(h)) for h in headings) / len(headings)
    variance = max(0.0, 1 - math.hypot(ms, mc))
    return math.degrees(math.sqrt(variance * 2))


def project_path(lat: float, lon: float, alt: float, track: float, gs: float, climb_fpm: float) -> list[dict]:
    out, dist = [], 0.0
    t = 0
    while t <= PROJECTION_HORIZON_S:
        la, lo = dest_point(lat, lon, track, dist)
        out.append({"t": t, "lat": la, "lon": lo, "alt_ft": max(0.0, alt + climb_fpm * t / 60)})
        dist += gs * (PROJECTION_STEP_S / 3600)
        t += PROJECTION_STEP_S
    return out


def logical_key(v: dict) -> str:
    if v["kind"] == "approach" and v.get("runway"):
        return f"approach:{v['runway']}"
    return v["id"]


def logical_label(v: dict) -> str:
    import re

    s = re.sub(r"\s*\([^)]*\)", "", v["name"]).split(",")[0]
    s = re.sub(r"\s*\([^)]*$", "", s)
    s = s.replace("Class B floor over the ", "").replace(" River ", " ")
    return s.strip()


def _contains(p: dict, v: dict) -> bool:
    return scn_geo.in_volume(p["lat"], p["lon"], p["alt_ft"], v)


def _stab_fresh(s: Snapshot) -> tuple[float, float]:
    return (
        clamp01(1 - heading_std_dev(s.track_history) / STABILITY_REFERENCE_DEG),
        clamp01(1 - s.data_age_s / FRESHNESS_REFERENCE_S),
    )


def _project_at(s: Snapshot, alt: float, rate: float, t: float) -> dict:
    la, lo = dest_point(s.lat, s.lon, s.track_deg, s.gs_kt * t / 3600)
    return {"t": t, "lat": la, "lon": lo, "alt_ft": max(0.0, alt + rate * t / 60)}


def _refine_entry(s: Snapshot, alt: float, rate: float, path: list[dict], idx: int, inside) -> dict:
    """Bisect between the last outside sample and the first inside one (engine refineEntry)."""
    if idx == 0:
        return path[0]
    lo, hi = path[idx - 1]["t"], path[idx]["t"]
    for _ in range(6):
        mid = (lo + hi) / 2
        if inside(_project_at(s, alt, rate, mid)):
            hi = mid
        else:
            lo = mid
    return _project_at(s, alt, rate, hi)


KIND_RANK = {"approach": 0, "departure": 1, "class_b_floor": 2}
SEV_RANK = {"advisory": 0, "caution": 1, "handoff": 2}


def _outranks(a: dict, b: dict) -> bool:
    if a["severity"] != b["severity"]:
        return SEV_RANK[a["severity"]] > SEV_RANK[b["severity"]]
    if a["kind"] != b["kind"]:
        return KIND_RANK[a["kind"]] < KIND_RANK[b["kind"]]
    if a["tte"] != b["tte"]:
        return a["tte"] < b["tte"]
    return a["confidence"] > b["confidence"]


class ConflictEngine:
    """One alert per aircraft (keyed by hex), as in app/src/engine/conflictEngine.ts."""

    def __init__(self, volumes: list[dict] | None = None) -> None:
        self.volumes = volumes if volumes is not None else scn_geo.protected_volumes()
        self.active: dict[str, Alert] = {}
        self.alt_hist: dict[str, list[tuple[float, float]]] = {}
        self._anchor: dict[str, tuple[float, float]] = {}
        self._last_tick: float | None = None

    def reset(self) -> None:
        self.active.clear()
        self.alt_hist.clear()
        self._anchor.clear()
        self._last_tick = None

    def _estimate(self, s: Snapshot) -> tuple[float, float]:
        hist = self.alt_hist.get(s.hex)
        if hist and hist[-1][0] > s.t:
            hist = None
        hist = [h for h in (hist or []) if h[0] >= s.t - VR_WINDOW_S]
        if hist and hist[-1][0] == s.t:
            hist[-1] = (s.t, s.alt_ft)
        else:
            hist.append((s.t, s.alt_ft))
        self.alt_hist[s.hex] = hist
        rate, alt = fit_vertical_rate(hist, s.t)
        return rate, (alt if math.isfinite(alt) else s.alt_ft)

    def _class_b(self, s: Snapshot, rate: float, alt: float, v: dict) -> dict | None:
        threshold = v["floor_ft_msl"] - CLASS_B_MARGIN_FT
        stab, fresh = _stab_fresh(s)
        label = logical_label(v)
        inside = scn_geo.point_in_ring(s.lat, s.lon, v["ring"])
        if inside and alt >= threshold:
            depth = clamp01((alt - threshold) / CLASS_B_ALT_REFERENCE_FT)
            return {
                "severity": "handoff",
                "confidence": clamp01(0.5 * depth + 0.3 * stab + 0.2 * fresh),
                "reason": f"{s.reg}: At {round(alt / 10) * 10:,} ft inside {label}, at or above Class B "
                f"floor {v['floor_ft_msl']:,} - {CLASS_B_MARGIN_FT} ft without a recorded clearance.",
                "volume_id": v["id"],
                "tte": 0,
                "lat": s.lat,
                "lon": s.lon,
                "alt": alt,
                "kind": v["kind"],
                "label": label,
            }
        if rate <= 0:
            return None
        path = project_path(s.lat, s.lon, alt, s.track_deg, s.gs_kt, rate)

        def reached(p: dict) -> bool:
            return p["alt_ft"] >= threshold and scn_geo.point_in_ring(p["lat"], p["lon"], v["ring"])

        idx = next((i for i, p in enumerate(path) if reached(p)), -1)
        if idx == -1:
            return None
        hit = _refine_entry(s, alt, rate, path, idx, reached)
        depth = clamp01(rate / VR_MAX_FPM)
        return {
            "severity": "caution",
            "confidence": clamp01(0.5 * depth + 0.3 * stab + 0.2 * fresh),
            "reason": f"{s.reg}: Climbing {round(rate):,} fpm; projected to reach Class B floor in "
            f"{round(hit['t'])} s.",
            "volume_id": v["id"],
            "tte": hit["t"],
            "lat": hit["lat"],
            "lon": hit["lon"],
            "alt": hit["alt_ft"],
            "kind": v["kind"],
            "label": label,
        }

    def _projected(
        self, s: Snapshot, alt: float, rate: float, path: list[dict], group: list[dict]
    ) -> dict | None:
        stab, fresh = _stab_fresh(s)
        best: tuple[int, dict] | None = None
        for v in group:
            idx = next((i for i, p in enumerate(path) if _contains(p, v)), -1)
            if idx != -1 and (best is None or idx < best[0]):
                best = (idx, v)
        if best:
            idx, v = best
            entry = _refine_entry(s, alt, rate, path, idx, lambda p, v=v: _contains(p, v))
            max_depth = 0.0
            for p in path[idx:]:
                if not _contains(p, v):
                    break
                max_depth = max(
                    max_depth, great_circle_dist_nm(path[idx]["lat"], path[idx]["lon"], p["lat"], p["lon"])
                )
            depth = clamp01(max_depth / DEPTH_REFERENCE_NM)
            band = "arrival glidepath band" if v["kind"] == "approach" else "departure altitude band"
            return {
                "severity": "handoff",
                "confidence": clamp01(0.5 * depth + 0.3 * stab + 0.2 * fresh),
                "reason": f"{s.reg}: Projected path crosses {logical_label(v)} at {round(entry['alt_ft']):,} ft - "
                f"inside the {band} ({v['floor_ft_msl']:,}-{v['ceiling_ft_msl']:,} ft) in "
                f"{round(entry['t'])} s.",
                "volume_id": v["id"],
                "tte": entry["t"],
                "lat": entry["lat"],
                "lon": entry["lon"],
                "alt": entry["alt_ft"],
                "kind": v["kind"],
                "label": logical_label(v),
            }
        min_d, nearest = math.inf, None
        for v in group:
            for p in path:
                if p["alt_ft"] < v["floor_ft_msl"] or p["alt_ft"] > v["ceiling_ft_msl"]:
                    continue
                d = scn_geo.min_dist_to_ring_nm(p["lat"], p["lon"], v["ring"])
                if d < min_d:
                    min_d, nearest = d, v
        if nearest is None:
            return None
        sev = "caution" if min_d <= NEAR_MISS_NM else "advisory" if min_d <= ADVISORY_NM else None
        if sev is None:
            return None
        prox = clamp01(1 - min_d / ADVISORY_NM)
        return {
            "severity": sev,
            "confidence": clamp01(0.5 * prox + 0.3 * stab + 0.2 * fresh),
            "reason": f"{s.reg}: projected path passes within {min_d:.2f} nm of {logical_label(nearest)}.",
            "volume_id": nearest["id"],
            "tte": PROJECTION_HORIZON_S,
            "lat": s.lat,
            "lon": s.lon,
            "alt": s.alt_ft,
            "kind": nearest["kind"],
            "label": logical_label(nearest),
        }

    def tick(self, snaps: list[Snapshot], now: float) -> list[Alert]:
        if self._last_tick is not None and now < self._last_tick:
            self.reset()
        self._last_tick = now
        seen: set[str] = set()
        groups: dict[str, list[dict]] = {}
        for v in self.volumes:
            groups.setdefault(logical_key(v), []).append(v)
        for s in snaps:
            rate, alt = self._estimate(s)
            path = project_path(s.lat, s.lon, alt, s.track_deg, s.gs_kt, rate)
            cands = []
            for group in groups.values():
                c = (
                    self._class_b(s, rate, alt, group[0])
                    if group[0]["kind"] == "class_b_floor"
                    else self._projected(s, alt, rate, path, group)
                )
                if c:
                    cands.append(c)
            best = None
            for c in cands:
                if best is None or _outranks(c, best):
                    best = c
            existing = self.active.get(s.hex)
            since = now - existing._last_real_tick if existing else math.inf
            held = bool(existing and existing.severity == "handoff" and 0 <= since < HYSTERESIS_S)
            if best and not (held and best["severity"] != "handoff"):
                also = sorted(
                    {
                        c["label"]
                        for c in cands
                        if c is not best and c["severity"] == best["severity"] and c["label"] != best["label"]
                    }
                )
                reason = best["reason"] + (f" Also overlaps: {', '.join(also)}." if also else "")
                self.active[s.hex] = Alert(
                    id=s.hex,
                    hex=s.hex,
                    reg=s.reg,
                    volume_id=best["volume_id"],
                    severity=best["severity"],
                    confidence=best["confidence"],
                    reason=reason,
                    time_to_entry_s=best["tte"],
                    entry_lat=best["lat"],
                    entry_lon=best["lon"],
                    entry_alt_ft=best["alt"],
                    first_seen_t=existing.first_seen_t if existing else now,
                    last_seen_t=now,
                    _last_real_tick=now,
                    also_volumes=also,
                )
                self._anchor[s.hex] = (now, best["tte"])
                seen.add(s.hex)
            elif existing and held:
                t_a, tte_a = self._anchor[s.hex]
                existing.time_to_entry_s = max(0.0, tte_a - (now - t_a))
                existing.last_seen_t = now
                seen.add(s.hex)
            else:
                self.active.pop(s.hex, None)
        for key in list(self.active):
            if key not in seen:
                del self.active[key]
        return list(self.active.values())


def run_engine(aircraft: list[dict], t0: float, t1: float, step_s: float = 1.0) -> list[dict]:
    """Tick the engine over [t0, t1] and return one record per distinct (aircraft, logical volume, severity)
    episode: first_seen_t, last t seen, peak confidence and the time-to-entry at first sight."""
    eng = ConflictEngine()
    episodes: dict[tuple[str, str, str], dict] = {}
    t = t0
    while t <= t1 + 1e-9:
        snaps = [s for s in (interpolate(a, t) for a in aircraft) if s]
        for al in eng.tick(snaps, t):
            k = (al.reg, logical_key(next(v for v in eng.volumes if v["id"] == al.volume_id)), al.severity)
            ep = episodes.get(k)
            if ep is None:
                episodes[k] = {
                    **al.public(),
                    "t_first": t,
                    "t_last": t,
                    "peak_confidence": al.confidence,
                    "lead_s_at_first": al.time_to_entry_s,
                }
            else:
                ep["t_last"] = t
                ep["peak_confidence"] = max(ep["peak_confidence"], al.confidence)
        t += step_s
    for ep in episodes.values():
        ep["peak_confidence"] = round(ep["peak_confidence"], 4)
    return sorted(episodes.values(), key=lambda e: e["t_first"])
