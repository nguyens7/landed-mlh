import { describe, expect, it } from "vitest";
import { ConflictEngine } from "./conflictEngine";
import { loadProtectedVolumes, loadReplay, snapshotAt } from "./testFixtures";
import type { AircraftSnapshot, ProtectedVolume } from "./types";

function aircraft(overrides: Partial<AircraftSnapshot> = {}): AircraftSnapshot {
  return {
    hex: "TEST01",
    reg: "N000TEST",
    simulated: true,
    t: 0,
    lat: 40.75,
    lon: -73.95,
    alt_ft: 400,
    gs_kt: 90,
    track_deg: 90,
    climb_fpm: 0,
    track_history: [90, 90, 90, 90],
    data_age_s: 0,
    ...overrides,
  };
}

function square(east = -73.8): ProtectedVolume {
  return {
    id: "test_vol",
    name: "Test Volume",
    kind: "approach",
    runway: "22",
    floor_ft_msl: 0,
    ceiling_ft_msl: 3000,
    source: "test",
    approximate: true,
    ring: [
      [-73.9, 40.7],
      [-73.9, 40.8],
      [east, 40.8],
      [east, 40.7],
      [-73.9, 40.7],
    ],
  };
}

const first = (ac: AircraftSnapshot, v: ProtectedVolume) => new ConflictEngine().tick([ac], [v], ac.t)[0];

describe("confidence is geometry-derived", () => {
  it("scores a sustained, deep, fresh penetration >= 0.85, even right after a turn", () => {
    expect(first(aircraft(), square()).confidence).toBeGreaterThanOrEqual(0.85);
    expect(first(aircraft({ track_history: [45, 45, 90, 90, 90] }), square()).confidence).toBeGreaterThanOrEqual(0.85);
  });

  it("scores a marginal clip of a thin sliver low", () => {
    const a = first(aircraft({ lon: -73.93 }), square(-73.8984));
    expect(a.severity).toBe("handoff");
    expect(a.confidence).toBeLessThan(0.4);
  });

  it("scores a stale track low however deep the penetration", () => {
    expect(first(aircraft({ data_age_s: 9 }), square()).confidence).toBeLessThan(0.4);
  });
});

describe("active runway config", () => {
  it("ignores Rwy 4 departures and Rwy 31 arrivals by default", () => {
    const [medevac] = loadReplay("sim_medevac.json");
    const volumes = loadProtectedVolumes();
    const engine = new ConflictEngine();
    const legacy = new ConflictEngine({ arrivals: ["22", "31"], departures: ["4", "13"] });
    let sawLegacyAlso = false;
    for (let i = 0; i < medevac.points.length; i++) {
      const snap = snapshotAt(medevac, i);
      const a = engine.tick([snap], volumes, snap.t)[0];
      if (a) expect(a.reason).not.toMatch(/Rwy 4|Rwy 31/);
      if (legacy.tick([snap], volumes, snap.t)[0]?.reason.includes("Rwy 4 departure")) sawLegacyAlso = true;
    }
    expect(sawLegacyAlso).toBe(true);
  });

  it("keeps the medevac handoff confidence high on the straight-in final", () => {
    const [medevac] = loadReplay("sim_medevac.json");
    const volumes = loadProtectedVolumes();
    const engine = new ConflictEngine();
    const confs: number[] = [];
    for (let i = 0; i < medevac.points.length; i++) {
      const snap = snapshotAt(medevac, i);
      const a = engine.tick([snap], volumes, snap.t)[0];
      // from the second turn onto final until just before entry (after that it is inside, not approaching)
      if (a?.severity === "handoff" && snap.t >= 400 && snap.t <= 448) confs.push(a.confidence);
    }
    expect(Math.min(...confs)).toBeGreaterThanOrEqual(0.85);
  });
});
