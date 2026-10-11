// Active runway configuration: which approach and departure volumes the engine evaluates.
// Pure TypeScript, no React. The Class B floor has no runway and is always active.

import type { ProtectedVolume } from "./types";

export interface RunwayConfig {
  /** Runways in use for arrivals, e.g. ["22"]: only their approach (final) volumes are evaluated. */
  arrivals: string[];
  /** Runways in use for departures, e.g. ["13"]: only their departure corridors are evaluated. */
  departures: string[];
}

/** Demo configuration: arrive Rwy 22, depart Rwy 13. */
export const DEFAULT_RUNWAY_CONFIG: RunwayConfig = { arrivals: ["22"], departures: ["13"] };

export function isVolumeActive(v: ProtectedVolume, cfg: RunwayConfig): boolean {
  if (v.kind === "class_b_floor" || !v.runway) return true;
  return (v.kind === "approach" ? cfg.arrivals : cfg.departures).includes(v.runway);
}

export function activeVolumes(volumes: ProtectedVolume[], cfg: RunwayConfig = DEFAULT_RUNWAY_CONFIG): ProtectedVolume[] {
  return volumes.filter((v) => isVolumeActive(v, cfg));
}
