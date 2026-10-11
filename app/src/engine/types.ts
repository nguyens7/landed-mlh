// Pure data types for the conflict engine. No React, no DOM.

export type Severity = "advisory" | "caution" | "handoff";

/** The engine's view of one aircraft at a simulation instant. Built by the store from
 * the replay data (interpolated position + locally-derived climb rate), never from React
 * state directly, so the engine stays decoupled from rendering. */
export interface AircraftSnapshot {
  hex: string;
  reg: string;
  type?: string;
  simulated: boolean;
  /** Simulation time (s from window start) this snapshot represents. */
  t: number;
  lat: number;
  lon: number;
  alt_ft: number;
  gs_kt: number;
  track_deg: number;
  /** Display-only vertical rate (ft/min) from the last two points. The engine does NOT use
   * it: it fits its own smoothed rate from per-aircraft altitude history (verticalRate.ts). */
  climb_fpm: number;
  /** Track heading (deg) of the last few points, oldest first, for stability scoring. */
  track_history: number[];
  /** Seconds since this aircraft last had a real data point (data freshness). */
  data_age_s: number;
}

export interface ProtectedVolume {
  id: string;
  name: string;
  kind: "approach" | "departure" | "class_b_floor";
  runway?: string | null;
  floor_ft_msl: number;
  ceiling_ft_msl: number;
  source: string;
  approximate: boolean;
  /** Ring of [lon, lat] pairs, first === last, matching GeoJSON Polygon winding. */
  ring: [number, number][];
}

export interface Alert {
  id: string;
  aircraft: { hex: string; reg: string };
  volume_id: string;
  severity: Severity;
  confidence: number;
  reason: string;
  time_to_entry_s: number;
  entry_point: { lat: number; lon: number };
  entry_alt_ft: number;
  /** First simulation time (s) this specific aircraft/volume alert became active. */
  first_seen_t: number;
  /** Most recent simulation time (s) this alert was recomputed as still active. */
  last_seen_t: number;
  /** Additive: other protected volumes the aircraft also threatens at the same severity,
   * collapsed into this single per-aircraft alert (e.g. the Rwy 4 / 13 departure corridors
   * that overlap the Rwy 22 final). Human-readable labels. */
  also_volumes?: string[];
}

/** A single sample along a 90s forward projection. */
export interface ProjectedPoint {
  t_offset_s: number;
  lat: number;
  lon: number;
  alt_ft: number;
}
