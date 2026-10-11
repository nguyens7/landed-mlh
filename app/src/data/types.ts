export interface ReplayPoint {
  t: number;
  lat: number;
  lon: number;
  alt_ft_msl: number;
  gs_kt: number;
  track_deg: number;
}

export interface ReplayAircraft {
  hex: string;
  reg: string;
  type?: string;
  owner?: string | null;
  role_guess: string;
  simulated: boolean;
  /** Present on display-only aircraft (saturday_fixedwing.json); never fed to the conflict engine. */
  kind?: "fixed_wing";
  points: ReplayPoint[];
}

export interface ReplayFile {
  metadata: Record<string, unknown>;
  aircraft: ReplayAircraft[];
}

export interface GeoFeatureCollection {
  type: "FeatureCollection";
  features: GeoJSON.Feature[];
}
