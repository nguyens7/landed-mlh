// Shared helpers for engine tests: load the real public/data JSON from disk and turn it
// into the engine's input types. Not a .test.ts file, so vitest won't collect it directly.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { AircraftSnapshot, ProtectedVolume } from "./types";

const DATA_DIR = resolve(__dirname, "../../public/data");

interface ReplayPoint {
  t: number;
  lat: number;
  lon: number;
  alt_ft_msl: number;
  gs_kt: number;
  track_deg: number;
}

interface ReplayAircraft {
  hex: string;
  reg: string;
  type?: string;
  simulated: boolean;
  points: ReplayPoint[];
}

interface ReplayFile {
  metadata: Record<string, unknown>;
  aircraft: ReplayAircraft[];
}

export function loadReplay(name: "saturday.json" | "sim_medevac.json"): ReplayAircraft[] {
  const raw = readFileSync(resolve(DATA_DIR, "replay", name), "utf8");
  const parsed = JSON.parse(raw) as ReplayFile;
  return parsed.aircraft;
}

export function loadProtectedVolumes(): ProtectedVolume[] {
  const raw = readFileSync(resolve(DATA_DIR, "geo", "protected_volumes.geojson"), "utf8");
  const fc = JSON.parse(raw) as {
    features: {
      properties: Record<string, unknown>;
      geometry: { type: string; coordinates: number[][][] };
    }[];
  };
  return fc.features.map((f) => ({
    id: f.properties.id as string,
    name: f.properties.name as string,
    kind: f.properties.kind as ProtectedVolume["kind"],
    runway: (f.properties.runway as string | null) ?? null,
    floor_ft_msl: f.properties.floor_ft_msl as number,
    ceiling_ft_msl: f.properties.ceiling_ft_msl as number,
    source: f.properties.source as string,
    approximate: Boolean(f.properties.approximate),
    ring: f.geometry.coordinates[0].map(([lon, lat]) => [lon, lat] as [number, number]),
  }));
}

/** Build an AircraftSnapshot for point index `i` of a replay aircraft's point list,
 * deriving climb rate and track-history from the preceding real points (never future
 * points -- this mirrors what the live engine sees). */
export function snapshotAt(ac: ReplayAircraft, i: number): AircraftSnapshot {
  const p = ac.points[i];
  const prev = ac.points[Math.max(0, i - 1)];
  const dt = Math.max(0.5, p.t - prev.t);
  const climb_fpm = i === 0 ? 0 : ((p.alt_ft_msl - prev.alt_ft_msl) / dt) * 60;
  const history = ac.points.slice(Math.max(0, i - 4), i + 1).map((pp) => pp.track_deg);
  return {
    hex: ac.hex,
    reg: ac.reg,
    type: ac.type,
    simulated: ac.simulated,
    t: p.t,
    lat: p.lat,
    lon: p.lon,
    alt_ft: p.alt_ft_msl,
    gs_kt: p.gs_kt,
    track_deg: p.track_deg,
    climb_fpm,
    track_history: history,
    data_age_s: 0,
  };
}

export function pointInRing(lat: number, lon: number, ring: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersects = yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}
