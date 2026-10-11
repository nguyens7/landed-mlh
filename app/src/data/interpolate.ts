import type { AircraftSnapshot } from "../engine/types";
import type { ReplayAircraft } from "./types";

/** Longest gap (s) between bracketing real points that is still interpolated. Beyond this
 * the position would be fabricated (the replay has gaps of several minutes), so the aircraft
 * is treated as not tracked: not shown and not evaluated by the engine. */
export const MAX_INTERP_GAP_S = 30;

/** Interpolated "live" position of an aircraft at simulation time t, for rendering and
 * for feeding the conflict engine. Returns null if the aircraft isn't active at t
 * (before its first point or after its last) or if the bracketing real points are more
 * than MAX_INTERP_GAP_S apart. */
export function interpolateAircraft(ac: ReplayAircraft, t: number): AircraftSnapshot | null {
  const pts = ac.points;
  if (pts.length === 0) return null;
  if (t < pts[0].t || t > pts[pts.length - 1].t) return null;

  // binary search for the bracketing pair
  let lo = 0;
  let hi = pts.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (pts[mid].t <= t) lo = mid;
    else hi = mid;
  }
  const a = pts[lo];
  const b = pts[hi];
  const span = b.t - a.t;
  if (span > MAX_INTERP_GAP_S) return null;
  const frac = span > 0 ? (t - a.t) / span : 0;

  const lat = a.lat + (b.lat - a.lat) * frac;
  const lon = a.lon + (b.lon - a.lon) * frac;
  const alt_ft = a.alt_ft_msl + (b.alt_ft_msl - a.alt_ft_msl) * frac;
  const gs_kt = a.gs_kt + (b.gs_kt - a.gs_kt) * frac;
  const track_deg = interpolateHeading(a.track_deg, b.track_deg, frac);
  const climb_fpm = span > 0 ? ((b.alt_ft_msl - a.alt_ft_msl) / span) * 60 : 0;

  const historyStart = Math.max(0, lo - 4);
  const track_history = pts.slice(historyStart, lo + 1).map((p) => p.track_deg);

  return {
    hex: ac.hex,
    reg: ac.reg,
    type: ac.type,
    simulated: ac.simulated,
    t,
    lat,
    lon,
    alt_ft,
    gs_kt,
    track_deg,
    climb_fpm,
    track_history,
    data_age_s: Math.min(span, t - a.t),
  };
}

function interpolateHeading(a: number, b: number, frac: number): number {
  const diff = ((b - a + 540) % 360) - 180;
  return (a + diff * frac + 360) % 360;
}
