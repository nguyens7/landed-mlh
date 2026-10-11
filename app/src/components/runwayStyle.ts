// Pure helpers for the LaGuardia map styling (runway strips and volume states). No maplibre here
// so they can be unit tested in node.

import { DEFAULT_RUNWAY_CONFIG, type RunwayConfig } from "../engine/runwayConfig";
import { destPoint } from "../engine/geometry";

/** Real LGA runway length: both 4/22 and 13/31 are about 7,000 ft. */
export const RUNWAY_LENGTH_NM = 7000 / 6076.12;

export type VolumeState = "alert" | "active-arrival" | "active-departure" | "inactive";

interface VolumeProps {
  id?: string;
  kind?: string;
  runway?: string | null;
}

/** Style state for one protected volume. A volume is "alert" when an alert's volume shares its
 * kind and runway (all segments of that final light up together); otherwise the active config
 * decides: active arrivals are amber, the active departure is a subtle dashed outline, anything
 * else (inactive runway ends, Class B floor) is a muted gray outline. */
export function volumeState(
  p: VolumeProps,
  alertVolumeIds: ReadonlySet<string>,
  allProps: readonly VolumeProps[],
  cfg: RunwayConfig = DEFAULT_RUNWAY_CONFIG,
): VolumeState {
  const sameLogical = (q: VolumeProps) => q.kind === p.kind && (q.runway ?? null) === (p.runway ?? null);
  if (allProps.some((q) => q.id !== undefined && alertVolumeIds.has(q.id) && sameLogical(q))) return "alert";
  if (p.kind === "approach" && p.runway && cfg.arrivals.includes(p.runway)) return "active-arrival";
  if (p.kind === "departure" && p.runway && cfg.departures.includes(p.runway)) return "active-departure";
  return "inactive";
}

interface ThresholdProps {
  runway?: string;
  threshold_lat?: number;
  threshold_lon?: number;
  bearing_true?: number;
}

/** Runway strips from the approach-path thresholds: each landing threshold to the far end of the
 * same pavement (4/22 and 13/31). The runway extends ahead of the threshold on the landing
 * heading (`bearing_true`, e.g. 212 for Rwy 22). Labels sit at the landing threshold. */
export function runwayStrips(approachProps: readonly ThresholdProps[]): {
  lines: [number, number][][];
  labels: { name: string; lon: number; lat: number }[];
} {
  const lines: [number, number][][] = [];
  const labels: { name: string; lon: number; lat: number }[] = [];
  for (const p of approachProps) {
    if (p.threshold_lat === undefined || p.threshold_lon === undefined || p.bearing_true === undefined) continue;
    const far = destPoint(p.threshold_lat, p.threshold_lon, p.bearing_true, RUNWAY_LENGTH_NM);
    lines.push([
      [p.threshold_lon, p.threshold_lat],
      [far.lon, far.lat],
    ]);
    labels.push({ name: `Runway ${p.runway}`, lon: p.threshold_lon, lat: p.threshold_lat });
  }
  return { lines, labels };
}
