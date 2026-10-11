import type { ProtectedVolume } from "../engine/types";
import type { GeoFeatureCollection, ReplayAircraft, ReplayFile } from "./types";

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`failed to load ${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export async function loadReplayData(): Promise<{ aircraft: ReplayAircraft[]; windowSeconds: number }> {
  const [saturday, sim] = await Promise.all([
    fetchJson<ReplayFile>("/data/replay/saturday.json"),
    fetchJson<ReplayFile>("/data/replay/sim_medevac.json"),
  ]);
  const windowSeconds = Number(saturday.metadata.window_seconds ?? 900);
  return { aircraft: [...saturday.aircraft, ...sim.aircraft], windowSeconds };
}

/** Display-only airliners near LGA. Optional: a missing file just means no airliner layer. */
export async function loadFixedWing(): Promise<ReplayAircraft[]> {
  try {
    const res = await fetch("/data/replay/saturday_fixedwing.json");
    if (!res.ok) return [];
    return ((await res.json()) as ReplayFile).aircraft;
  } catch {
    return [];
  }
}

export async function loadGeoData(): Promise<{
  corridors: GeoFeatureCollection;
  protectedVolumes: GeoFeatureCollection;
  approachPaths: GeoFeatureCollection;
  referencePoints: GeoFeatureCollection;
  volumes: ProtectedVolume[];
}> {
  const [corridors, protectedVolumes, approachPaths, referencePoints] = await Promise.all([
    fetchJson<GeoFeatureCollection>("/data/geo/corridors.geojson"),
    fetchJson<GeoFeatureCollection>("/data/geo/protected_volumes.geojson"),
    fetchJson<GeoFeatureCollection>("/data/geo/approach_paths.geojson"),
    fetchJson<GeoFeatureCollection>("/data/geo/reference_points.geojson"),
  ]);

  const volumes: ProtectedVolume[] = protectedVolumes.features
    .filter((f) => f.geometry.type === "Polygon")
    .map((f) => {
      const props = f.properties as Record<string, unknown>;
      const coords = (f.geometry as GeoJSON.Polygon).coordinates[0] as [number, number][];
      return {
        id: String(props.id),
        name: String(props.name),
        kind: props.kind as ProtectedVolume["kind"],
        runway: (props.runway as string | null) ?? null,
        floor_ft_msl: Number(props.floor_ft_msl),
        ceiling_ft_msl: Number(props.ceiling_ft_msl),
        source: String(props.source),
        approximate: Boolean(props.approximate),
        ring: coords,
      };
    });

  return { corridors, protectedVolumes, approachPaths, referencePoints, volumes };
}
