// The conflict engine. Pure TypeScript, no React.
//
// Two kinds of trigger (SPEC.md section 2, "Mandatory handoff triggers"):
//
// 1. Approach / departure volumes: the 90 s projected path is intersected with the
//    volume's polygon + altitude band. The projection starts from the smoothed altitude
//    and the least-squares vertical rate (see verticalRate.ts), not from the raw
//    two-point climb rate. Segments of the same runway's final (lga22_final_seg0..6) are
//    one logical volume: one alert per aircraft per runway, reporting the segment entered.
//
// 2. Class B floor: NOT a projected-volume intersection. Handoff when the smoothed
//    *current* altitude >= floor - 100 ft while the aircraft is inside the lateral
//    polygon (altitude >= Class B floor - 100 without a human clearance). Caution when
//    the projection would reach floor - 100 ft inside the polygon within 90 s on a
//    sustained climb (rate above the deadband).
//
// Confidence formula (documented, no hardcoded confidences per SPEC.md 2.2):
//
//   confidence = freshnessScore * (0.65 * depthScore + 0.35 * stabilityScore)
//
//   depthScore      - geometric evidence, the dominant term. Projected volumes: how far the
//                      straight-line path stays inside the logical volume (all segments of
//                      the runway's final together) after the first entry, measured on a path
//                      extended to 2x the 90 s horizon so a late entry is not penalized for
//                      the horizon cutting the penetration short; normalized by 0.5 nm, so a
//                      half-mile sustained penetration is full depth and a clip is near 0.
//                      Class B handoff: 0.5 plus half of how far the smoothed altitude is above
//                      floor - 100, normalized by 300 ft; freshness is not applied (the rule
//                      reads current altitude, so a sparse sample gap must not zero it). Class B caution: the sustained climb rate
//                      normalized by the 1,500 fpm clamp. Near-miss (caution/advisory):
//                      proximity, 1 - dist / 1 nm.
//   stabilityScore  - 1 - (circular std-dev of the last few track headings / 60 deg). A turn
//                      onto final lowers it briefly (a 45 deg jump is about 0.7); it cannot
//                      outweigh depth.
//   freshnessScore  - a gate, not a weight: 1 while data_age_s <= 3 s (normal ADS-B cadence),
//                      then falling linearly to 0 at 10 s, so a stale track is low confidence
//                      however deep the projected penetration.
//
// All terms are in [0, 1] and the depth/stability weights sum to 1, so confidence is in
// [0, 1]. A sustained, deep, fresh penetration scores >= 0.85; a marginal clip or a stale
// track scores < 0.4.
//
// Only volumes active under the RunwayConfig (runwayConfig.ts; default arrive 22, depart 13)
// are evaluated. The Class B floor is always active.
//
// Severity for projected volumes:
//   "handoff"  - the 90 s projection enters the polygon + altitude band.
//   "caution"  - no projected entry, but the projection passes within NEAR_MISS_NM.
//   "advisory" - no projected entry, but within ADVISORY_NM.
//
// One alert per aircraft: overlapping volumes collapse into the highest-severity candidate
// (ties: approach, then departure, then class B floor); the others are listed in
// `also_volumes`. time_to_entry_s is refined between projection samples so it counts down
// smoothly, and held alerts count down by elapsed sim time.
//
// Hysteresis: once an aircraft's handoff is active it is kept alive for
// HYSTERESIS_S seconds after the last tick that re-derived it, so one noisy tick does
// not make it flicker. Only the on->off transition is delayed.

import {
  destPoint,
  distanceNm,
  distanceToPolygonNm,
  headingStdDev,
  pointInPolygon,
} from "./geometry";
import { activeVolumes, DEFAULT_RUNWAY_CONFIG, type RunwayConfig } from "./runwayConfig";
import type { AircraftSnapshot, Alert, ProjectedPoint, ProtectedVolume, Severity } from "./types";
import { fitVerticalRate, VR_MAX_FPM, VR_WINDOW_S, type AltSample, type VerticalEstimate } from "./verticalRate";

export const PROJECTION_HORIZON_S = 90;
export const PROJECTION_STEP_S = 3;
export const NEAR_MISS_NM = 0.3;
export const ADVISORY_NM = 1.0;
export const HYSTERESIS_S = 12;
/** Handoff when smoothed altitude >= Class B floor minus this margin (SPEC.md section 2). */
export const CLASS_B_MARGIN_FT = 100;
const DEPTH_REFERENCE_NM = 0.5;
const DEPTH_PATH_HORIZON_S = 2 * PROJECTION_HORIZON_S;
/** Track data up to this old is treated as fully fresh (normal ADS-B update cadence). */
const FRESH_GRACE_S = 3;
const CLASS_B_ALT_REFERENCE_FT = 300;
const STABILITY_REFERENCE_DEG = 60;
const FRESHNESS_REFERENCE_S = 10;

export function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}

/** The documented confidence formula; see the header comment. */
export function combineConfidence(depth: number, stability: number, freshness: number): number {
  return clamp01(freshness * (0.65 * clamp01(depth) + 0.35 * clamp01(stability)));
}

/** Project an aircraft's path forward assuming constant ground speed, track, and climb
 * rate -- the straight-line/constant-rate model SPEC.md section 2 calls for. */
export function projectPath(
  ac: AircraftSnapshot,
  horizonS = PROJECTION_HORIZON_S,
  stepS = PROJECTION_STEP_S,
): ProjectedPoint[] {
  const out: ProjectedPoint[] = [];
  let distNm = 0;
  for (let t = 0; t <= horizonS; t += stepS) {
    const { lat, lon } = destPoint(ac.lat, ac.lon, ac.track_deg, distNm);
    const alt_ft = Math.max(0, ac.alt_ft + (ac.climb_fpm * t) / 60);
    out.push({ t_offset_s: t, lat, lon, alt_ft });
    distNm += ac.gs_kt * (stepS / 3600);
  }
  return out;
}

function volumeContains(p: ProjectedPoint, v: ProtectedVolume): boolean {
  return p.alt_ft >= v.floor_ft_msl && p.alt_ft <= v.ceiling_ft_msl && pointInPolygon(p.lat, p.lon, v.ring);
}

/** Penetration depth: distance the straight-line path (extended past the 90 s horizon) stays
 * inside the logical volume after the first entry, normalized by DEPTH_REFERENCE_NM. */
function depthScoreFor(ac: AircraftSnapshot, entryT: number, group: ProtectedVolume[]): number {
  const entry = projectAt(ac, entryT);
  let maxDepthNm = 0;
  for (let t = entryT; t <= DEPTH_PATH_HORIZON_S; t += PROJECTION_STEP_S) {
    const p = projectAt(ac, t);
    if (!group.some((v) => volumeContains(p, v))) break;
    maxDepthNm = Math.max(maxDepthNm, distanceNm(entry.lat, entry.lon, p.lat, p.lon));
  }
  return clamp01(maxDepthNm / DEPTH_REFERENCE_NM);
}

const fmt = (n: number) => Math.round(n).toLocaleString("en-US");

/** Logical-volume key: segments of one runway's final share a key; everything else is its own. */
export function logicalVolumeKey(v: ProtectedVolume): string {
  if (v.kind === "approach" && v.runway) return `approach:${v.runway}`;
  return v.id;
}

/** "LGA Rwy 22 final, 4-5 nm from threshold" -> "LGA Rwy 22 final". */
function logicalLabel(v: ProtectedVolume): string {
  return v.name
    .replace(/\s*\([^)]*\)/g, "") // balanced parentheticals, e.g. "(modeled straight-out, 5 nm)"
    .split(",")[0]
    .replace(/\s*\([^)]*$/, "") // any unbalanced trailing paren
    .replace(/^Class B floor over the /, "")
    .replace(/ River /, " ")
    .trim();
}

/** Where along the segment (nm from the threshold) a point is, for names like
 * "... 4-5 nm from threshold". Segment rings are quads whose ring[0..1] edge is the far end
 * and ring[2..3] the near end; the result is only trusted if the quad's length matches the
 * named band. Returns null when the name or geometry does not support it. */
function nmOutAt(v: ProtectedVolume, lat: number, lon: number): number | null {
  const m = /(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?) nm/.exec(v.name);
  if (!m || v.ring.length < 5) return null;
  const lo = Number(m[1]);
  const hi = Number(m[2]);
  const mid = (a: [number, number], b: [number, number]) => ({ lon: (a[0] + b[0]) / 2, lat: (a[1] + b[1]) / 2 });
  const far = mid(v.ring[0], v.ring[1]);
  const near = mid(v.ring[2], v.ring[3]);
  const lenNm = distanceNm(near.lat, near.lon, far.lat, far.lon);
  if (lenNm <= 0 || Math.abs(lenNm - (hi - lo)) > 0.3 * (hi - lo)) return null;
  const dNear = distanceNm(lat, lon, near.lat, near.lon);
  const dFar = distanceNm(lat, lon, far.lat, far.lon);
  const frac = clamp01(dNear / (dNear + dFar));
  return lo + frac * (hi - lo);
}

interface Candidate {
  severity: Severity;
  confidence: number;
  /** Reason text for a given countdown, so held alerts can be re-rendered each tick. */
  reasonFor: (timeToEntryS: number) => string;
  kind: ProtectedVolume["kind"];
  label: string;
  volume_id: string;
  time_to_entry_s: number;
  entry_point: { lat: number; lon: number };
  entry_alt_ft: number;
}

interface TrackedAlert extends Alert {
  _lastRealTick: number;
  /** Countdown anchor: time_to_entry_s was `_anchorTte` at sim time `_anchorT`. */
  _anchorT: number;
  _anchorTte: number;
  _reasonFor: (timeToEntryS: number) => string;
}

const KIND_RANK: Record<ProtectedVolume["kind"], number> = { approach: 0, departure: 1, class_b_floor: 2 };
const SEVERITY_RANK: Record<Severity, number> = { advisory: 0, caution: 1, handoff: 2 };

/** True when `a` should be the primary volume of an aircraft's single alert: highest severity,
 * then approach over departure over class B floor, then soonest entry, then confidence. */
function outranks(a: Candidate, b: Candidate): boolean {
  if (a.severity !== b.severity) return SEVERITY_RANK[a.severity] > SEVERITY_RANK[b.severity];
  if (a.kind !== b.kind) return KIND_RANK[a.kind] < KIND_RANK[b.kind];
  if (a.time_to_entry_s !== b.time_to_entry_s) return a.time_to_entry_s < b.time_to_entry_s;
  return a.confidence > b.confidence;
}

/** Position/altitude of the constant-rate projection at an arbitrary offset (s). */
function projectAt(ac: AircraftSnapshot, t: number): ProjectedPoint {
  const { lat, lon } = destPoint(ac.lat, ac.lon, ac.track_deg, (ac.gs_kt * t) / 3600);
  return { t_offset_s: t, lat, lon, alt_ft: Math.max(0, ac.alt_ft + (ac.climb_fpm * t) / 60) };
}

/** The projection is sampled every PROJECTION_STEP_S, which would make the countdown jump in
 * 3 s steps. Bisect between the last outside sample and the first inside one to find the
 * entry to ~0.05 s, so time-to-entry decreases smoothly as the aircraft approaches. */
function refineEntry(
  ac: AircraftSnapshot,
  path: ProjectedPoint[],
  idx: number,
  inside: (p: ProjectedPoint) => boolean,
): ProjectedPoint {
  if (idx === 0) return path[0];
  let lo = path[idx - 1].t_offset_s; // outside
  let hi = path[idx].t_offset_s; // inside
  for (let i = 0; i < 6; i++) {
    const mid = (lo + hi) / 2;
    if (inside(projectAt(ac, mid))) hi = mid;
    else lo = mid;
  }
  return projectAt(ac, hi);
}

function stabilityFreshness(ac: AircraftSnapshot): { stability: number; freshness: number } {
  return {
    stability: clamp01(1 - headingStdDev(ac.track_history) / STABILITY_REFERENCE_DEG),
    freshness: clamp01(1 - Math.max(0, ac.data_age_s - FRESH_GRACE_S) / (FRESHNESS_REFERENCE_S - FRESH_GRACE_S)),
  };
}

export class ConflictEngine {
  private active = new Map<string, TrackedAlert>();
  private altHistory = new Map<string, AltSample[]>();
  private lastTickT: number | null = null;

  /** Only volumes active under `runwayConfig` are evaluated (the Class B floor always is). */
  private runwayConfig: RunwayConfig;

  constructor(runwayConfig: RunwayConfig = DEFAULT_RUNWAY_CONFIG) {
    this.runwayConfig = runwayConfig;
  }

  setRunwayConfig(cfg: RunwayConfig): void {
    this.runwayConfig = cfg;
  }

  /** Record this tick's altitude and return the smoothed estimate for the aircraft. */
  private estimate(ac: AircraftSnapshot): VerticalEstimate {
    let hist = this.altHistory.get(ac.hex);
    // Time went backwards (scrub/seek/replay restart): the old samples are meaningless.
    if (hist && hist.length > 0 && hist[hist.length - 1].t > ac.t) hist = undefined;
    hist = (hist ?? []).filter((s) => s.t >= ac.t - VR_WINDOW_S);
    const last = hist[hist.length - 1];
    if (last && last.t === ac.t) last.alt_ft = ac.alt_ft;
    else hist.push({ t: ac.t, alt_ft: ac.alt_ft });
    this.altHistory.set(ac.hex, hist);
    const est = fitVerticalRate(hist, ac.t);
    return Number.isFinite(est.alt_ft) ? est : { ...est, alt_ft: ac.alt_ft };
  }

  private evaluateClassB(ac: AircraftSnapshot, est: VerticalEstimate, v: ProtectedVolume): Candidate | null {
    const threshold = v.floor_ft_msl - CLASS_B_MARGIN_FT;
    const { stability, freshness } = stabilityFreshness(ac);
    const label = logicalLabel(v);
    const inside = pointInPolygon(ac.lat, ac.lon, v.ring);

    if (inside && est.alt_ft >= threshold) {
      // The rule is a current-altitude test, so a sparse sample gap (interpolated data_age_s)
      // must not gate it to 0.00: freshness is not applied. Depth starts at 0.5 when the rule
      // has just fired and reaches 1 at CLASS_B_ALT_REFERENCE_FT above floor - 100.
      const depth = 0.5 + 0.5 * clamp01((est.alt_ft - threshold) / CLASS_B_ALT_REFERENCE_FT);
      const confidence = combineConfidence(depth, stability, 1);
      return {
        severity: "handoff",
        confidence,
        reasonFor: () =>
          `${ac.reg}: At ${fmt(Math.round(est.alt_ft / 10) * 10)} ft inside ${label}, at or above Class B floor ` +
          `${fmt(v.floor_ft_msl)} − ${CLASS_B_MARGIN_FT} ft without a recorded clearance.`,
        kind: v.kind,
        label,
        volume_id: v.id,
        time_to_entry_s: 0,
        entry_point: { lat: ac.lat, lon: ac.lon },
        entry_alt_ft: est.alt_ft,
      };
    }

    // Caution: sustained climb whose projection reaches floor - 100 inside the polygon.
    if (est.rate_fpm <= 0) return null;
    const smoothed = { ...ac, alt_ft: est.alt_ft, climb_fpm: est.rate_fpm };
    const path = projectPath(smoothed);
    const reached = (p: ProjectedPoint) => p.alt_ft >= threshold && pointInPolygon(p.lat, p.lon, v.ring);
    const hitIdx = path.findIndex(reached);
    if (hitIdx === -1) return null;
    const hit = refineEntry(smoothed, path, hitIdx, reached);
    const depth = clamp01(est.rate_fpm / VR_MAX_FPM);
    const confidence = combineConfidence(depth, stability, freshness);
    return {
      severity: "caution",
      confidence,
      reasonFor: (tte) =>
        `${ac.reg}: Climbing ${fmt(est.rate_fpm)} fpm from ${fmt(Math.round(est.alt_ft / 10) * 10)} ft; projected to reach ` +
        `Class B floor ${fmt(v.floor_ft_msl)} − ${CLASS_B_MARGIN_FT} ft inside ${label} in ${Math.round(tte)} s ` +
        `without a recorded clearance.`,
      kind: v.kind,
      label,
      volume_id: v.id,
      time_to_entry_s: hit.t_offset_s,
      entry_point: { lat: hit.lat, lon: hit.lon },
      entry_alt_ft: hit.alt_ft,
    };
  }

  private evaluateProjected(
    ac: AircraftSnapshot,
    path: ProjectedPoint[],
    group: ProtectedVolume[],
  ): Candidate | null {
    const { stability, freshness } = stabilityFreshness(ac);

    // Earliest projected entry across all segments of the logical volume.
    let best: { idx: number; v: ProtectedVolume } | null = null;
    for (const v of group) {
      const idx = path.findIndex((p) => volumeContains(p, v));
      if (idx !== -1 && (best === null || idx < best.idx)) best = { idx, v };
    }

    if (best) {
      const { idx, v } = best;
      const entry = refineEntry(ac, path, idx, (p) => volumeContains(p, v));
      const depth = depthScoreFor(ac, entry.t_offset_s, group);
      const confidence = combineConfidence(depth, stability, freshness);
      const nmOut = v.kind === "approach" ? nmOutAt(v, entry.lat, entry.lon) : null;
      const where =
        v.kind === "approach"
          ? nmOut !== null
            ? ` ${nmOut.toFixed(1)} nm from threshold`
            : ` (${v.name.split(",").slice(1).join(",").trim() || v.id})`
          : "";
      const band = `${fmt(v.floor_ft_msl)}–${fmt(v.ceiling_ft_msl)} ft`;
      const bandLabel = v.kind === "approach" ? "arrival glidepath band" : "departure altitude band";
      return {
        severity: "handoff",
        confidence,
        reasonFor: (tte) =>
          `${ac.reg}: Projected path crosses ${logicalLabel(v)}${where} at ${fmt(entry.alt_ft)} ft, ` +
          `inside the ${bandLabel} (${band}) in ${Math.round(tte)} s.`,
        kind: v.kind,
        label: logicalLabel(v),
        volume_id: v.id,
        time_to_entry_s: entry.t_offset_s,
        entry_point: { lat: entry.lat, lon: entry.lon },
        entry_alt_ft: entry.alt_ft,
      };
    }

    // Near-miss: only samples actually inside a segment's altitude band count.
    let minDistNm = Infinity;
    let nearest: ProtectedVolume | null = null;
    for (const v of group) {
      for (const p of path) {
        if (p.alt_ft < v.floor_ft_msl || p.alt_ft > v.ceiling_ft_msl) continue;
        const d = distanceToPolygonNm(p.lat, p.lon, v.ring);
        if (d < minDistNm) {
          minDistNm = d;
          nearest = v;
        }
      }
    }
    if (!nearest) return null;
    let severity: Severity | null = null;
    if (minDistNm <= NEAR_MISS_NM) severity = "caution";
    else if (minDistNm <= ADVISORY_NM) severity = "advisory";
    if (!severity) return null;
    const proximity = clamp01(1 - minDistNm / ADVISORY_NM);
    const confidence = combineConfidence(proximity, stability, freshness);
    return {
      severity,
      confidence,
      reasonFor: () => `${ac.reg}: projected path passes within ${minDistNm.toFixed(2)} nm of ${logicalLabel(nearest)}.`,
      kind: nearest.kind,
      label: logicalLabel(nearest),
      volume_id: nearest.id,
      time_to_entry_s: PROJECTION_HORIZON_S,
      entry_point: { lat: ac.lat, lon: ac.lon },
      entry_alt_ft: ac.alt_ft,
    };
  }

  /** Run one tick. `nowT` is simulation time in seconds. Returns the current alerts: at most
   * ONE per aircraft (overlapping volumes collapse into the highest-severity one; ties prefer
   * approach over departure over class B floor), including handoffs held by hysteresis. */
  tick(aircraft: AircraftSnapshot[], volumes: ProtectedVolume[], nowT: number): Alert[] {
    // Time went backwards (scrub/seek): nothing derived from the future may survive.
    if (this.lastTickT !== null && nowT < this.lastTickT) this.reset();
    this.lastTickT = nowT;

    const seenThisTick = new Set<string>();

    const groups = new Map<string, ProtectedVolume[]>();
    for (const v of activeVolumes(volumes, this.runwayConfig)) {
      const key = logicalVolumeKey(v);
      const g = groups.get(key);
      if (g) g.push(v);
      else groups.set(key, [v]);
    }

    for (const ac of aircraft) {
      const est = this.estimate(ac);
      const smoothed: AircraftSnapshot = { ...ac, alt_ft: est.alt_ft, climb_fpm: est.rate_fpm };
      const path = projectPath(smoothed);
      const key = ac.hex;
      const existing = this.active.get(key);

      const cands: Candidate[] = [];
      for (const group of groups.values()) {
        const cand =
          group[0].kind === "class_b_floor"
            ? this.evaluateClassB(ac, est, group[0])
            : this.evaluateProjected(smoothed, path, group);
        if (cand) cands.push(cand);
      }
      let best: Candidate | null = null;
      for (const c of cands) if (best === null || outranks(c, best)) best = c;

      // A live handoff is not downgraded or dropped until its hysteresis window passes.
      // A negative dt (time went backwards) never holds anything.
      const sinceReal = existing ? nowT - existing._lastRealTick : Infinity;
      const heldHandoff =
        existing !== undefined && existing.severity === "handoff" && sinceReal >= 0 && sinceReal < HYSTERESIS_S;

      if (best && !(heldHandoff && best.severity !== "handoff")) {
        const tte = best.time_to_entry_s;
        const also = Array.from(
          new Set(cands.filter((c) => c !== best && c.severity === best.severity).map((c) => c.label)),
        ).filter((l) => l !== best.label);
        const reason = best.reasonFor(tte);
        this.active.set(key, {
          id: key,
          aircraft: { hex: ac.hex, reg: ac.reg },
          volume_id: best.volume_id,
          severity: best.severity,
          confidence: best.confidence,
          reason: also.length > 0 ? `${reason} Also overlaps: ${also.join(", ")}.` : reason,
          time_to_entry_s: tte,
          entry_point: best.entry_point,
          entry_alt_ft: best.entry_alt_ft,
          first_seen_t: existing?.first_seen_t ?? nowT,
          last_seen_t: nowT,
          ...(also.length > 0 ? { also_volumes: also } : {}),
          _lastRealTick: nowT,
          _anchorT: nowT,
          _anchorTte: tte,
          _reasonFor: (t) => {
            const r = best.reasonFor(t);
            return also.length > 0 ? `${r} Also overlaps: ${also.join(", ")}.` : r;
          },
        });
        seenThisTick.add(key);
      } else if (existing && heldHandoff) {
        // Held by hysteresis: count the countdown down from the last computed value by the
        // elapsed sim time, so it keeps ticking smoothly and the reason never goes stale.
        const tte = Math.max(0, existing._anchorTte - (nowT - existing._anchorT));
        existing.time_to_entry_s = tte;
        existing.reason = existing._reasonFor(tte);
        existing.last_seen_t = nowT;
        seenThisTick.add(key);
      } else {
        this.active.delete(key);
      }
    }

    // Drop anything not touched this tick (aircraft left the scenario) -- defensive cleanup.
    for (const key of this.active.keys()) {
      if (!seenThisTick.has(key)) this.active.delete(key);
    }

    return Array.from(this.active.values()).map((a) => ({
      id: a.id,
      aircraft: a.aircraft,
      volume_id: a.volume_id,
      severity: a.severity,
      confidence: a.confidence,
      reason: a.reason,
      time_to_entry_s: a.time_to_entry_s,
      entry_point: a.entry_point,
      entry_alt_ft: a.entry_alt_ft,
      first_seen_t: a.first_seen_t,
      last_seen_t: a.last_seen_t,
      ...(a.also_volumes ? { also_volumes: a.also_volumes } : {}),
    }));
  }

  reset(): void {
    this.active.clear();
    this.altHistory.clear();
    this.lastTickT = null;
  }
}
