import { beforeEach, describe, expect, it } from "vitest";
import { ConflictEngine, projectPath } from "./conflictEngine";
import type { AircraftSnapshot, ProtectedVolume } from "./types";
import { loadProtectedVolumes, loadReplay, pointInRing, snapshotAt } from "./testFixtures";

function straightFlightSnapshot(overrides: Partial<AircraftSnapshot> = {}): AircraftSnapshot {
  return {
    hex: "TEST01",
    reg: "N000TEST",
    simulated: true,
    t: 0,
    lat: 40.75,
    lon: -73.95,
    alt_ft: 1000,
    gs_kt: 100,
    track_deg: 90,
    climb_fpm: 0,
    track_history: [90, 90, 90, 90],
    data_age_s: 0,
    ...overrides,
  };
}

function squareVolume(overrides: Partial<ProtectedVolume> = {}): ProtectedVolume {
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
      [-73.8, 40.8],
      [-73.8, 40.7],
      [-73.9, 40.7],
    ],
    ...overrides,
  };
}

describe("projectPath", () => {
  it("advances position east and altitude up for a climbing eastbound aircraft", () => {
    const ac = straightFlightSnapshot({ track_deg: 90, gs_kt: 120, climb_fpm: 600 });
    const path = projectPath(ac, 90, 30);
    expect(path.length).toBe(4); // t = 0, 30, 60, 90
    expect(path.at(-1)!.lon).toBeGreaterThan(path[0].lon);
    expect(path.at(-1)!.alt_ft).toBeCloseTo(1000 + 600 * 1.5, 0);
  });

  it("never projects altitude below 0", () => {
    const ac = straightFlightSnapshot({ alt_ft: 100, climb_fpm: -2000 });
    const path = projectPath(ac, 90, 30);
    for (const p of path) expect(p.alt_ft).toBeGreaterThanOrEqual(0);
  });
});

describe("ConflictEngine: synthetic scenarios", () => {
  let engine: ConflictEngine;
  beforeEach(() => {
    engine = new ConflictEngine();
  });

  it("fires a handoff alert when the projected path enters a protected volume", () => {
    // starts west of the box, heading east at a speed that reaches it within 90s
    const ac = straightFlightSnapshot({
      lat: 40.75,
      lon: -73.95,
      track_deg: 90,
      gs_kt: 200, // ~0.056 nm/s -> covers the ~2.6nm gap in ~45s
      alt_ft: 1000,
    });
    const alerts = engine.tick([ac], [squareVolume()], 0);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].severity).toBe("handoff");
    expect(alerts[0].confidence).toBeGreaterThan(0);
    expect(alerts[0].confidence).toBeLessThanOrEqual(1);
    expect(alerts[0].reason).toContain("N000TEST");
  });

  it("does not alert an aircraft flying away from every volume", () => {
    const ac = straightFlightSnapshot({ lat: 40.75, lon: -73.95, track_deg: 270, gs_kt: 120 });
    const alerts = engine.tick([ac], [squareVolume()], 0);
    expect(alerts).toHaveLength(0);
  });

  it("does not alert when the altitude band excludes the projected path", () => {
    const ac = straightFlightSnapshot({
      lat: 40.75,
      lon: -73.95,
      track_deg: 90,
      gs_kt: 200,
      alt_ft: 5000,
      climb_fpm: 0,
    });
    const vol = squareVolume({ floor_ft_msl: 0, ceiling_ft_msl: 3000 });
    const alerts = engine.tick([ac], [vol], 0);
    expect(alerts).toHaveLength(0);
  });

  it("applies hysteresis: a handoff alert survives one noisy tick where projection briefly clears", () => {
    const enteringAc = straightFlightSnapshot({ lat: 40.75, lon: -73.95, track_deg: 90, gs_kt: 200 });
    const firstTick = engine.tick([enteringAc], [squareVolume()], 0);
    expect(firstTick).toHaveLength(1);

    // next tick: same aircraft now briefly turned away (simulating ASR/track noise)
    const noisyAc = straightFlightSnapshot({ lat: 40.75, lon: -73.95, track_deg: 270, gs_kt: 200 });
    const secondTick = engine.tick([noisyAc], [squareVolume()], 2);
    expect(secondTick).toHaveLength(1); // held alive by hysteresis
    expect(secondTick[0].severity).toBe("handoff");

    // after the hysteresis window with no re-entry, it should clear
    const laterTick = engine.tick([noisyAc], [squareVolume()], 2 + 20);
    expect(laterTick).toHaveLength(0);
  });

  it("produces a caution alert for a near-miss that never actually enters the volume", () => {
    // passes just south of the box (box spans lat 40.7-40.8), never crossing into it
    const ac = straightFlightSnapshot({ lat: 40.69, lon: -73.95, track_deg: 90, gs_kt: 200 });
    const alerts = engine.tick([ac], [squareVolume()], 0);
    expect(alerts.length).toBeGreaterThanOrEqual(0);
    if (alerts.length > 0) {
      expect(["caution", "advisory"]).toContain(alerts[0].severity);
    }
  });
});

describe("ConflictEngine: sim medevac scenario (SPEC.md section 4, S2)", () => {
  it("triggers a handoff at least 45s before the aircraft actually enters the LGA22 approach volume", () => {
    const [medevac] = loadReplay("sim_medevac.json");
    const volumes = loadProtectedVolumes();
    // Track B splits the Rwy 22 final into glidepath segments; any of them counts.
    const lga22 = volumes.filter((v) => v.kind === "approach" && v.runway === "22");
    expect(lga22.length).toBeGreaterThan(0);
    const lga22Ids = new Set(lga22.map((v) => v.id));

    // ground truth: first real (non-projected) point actually inside the volume
    let actualEntryT: number | null = null;
    for (const p of medevac.points) {
      const inside = lga22.some(
        (v) =>
          p.alt_ft_msl >= v.floor_ft_msl &&
          p.alt_ft_msl <= v.ceiling_ft_msl &&
          pointInRing(p.lat, p.lon, v.ring),
      );
      if (inside) {
        actualEntryT = p.t;
        break;
      }
    }
    expect(actualEntryT).not.toBeNull();

    const engine = new ConflictEngine();
    let firstHandoffT: number | null = null;
    for (let i = 0; i < medevac.points.length; i++) {
      const snap = snapshotAt(medevac, i);
      const alerts = engine.tick([snap], volumes, snap.t);
      const handoff = alerts.find((a) => lga22Ids.has(a.volume_id) && a.severity === "handoff");
      if (handoff && firstHandoffT === null) {
        firstHandoffT = snap.t;
        break;
      }
    }

    expect(firstHandoffT).not.toBeNull();
    const leadTimeS = actualEntryT! - firstHandoffT!;
    expect(leadTimeS).toBeGreaterThanOrEqual(45);
  });
});

function classBVolume(): ProtectedVolume {
  return squareVolume({
    id: "class_b_test",
    name: "Class B floor over the Hudson River Exclusion",
    kind: "class_b_floor",
    runway: null,
    floor_ft_msl: 1300,
    ceiling_ft_msl: 7000,
  });
}

/** Tick a stationary aircraft inside the square volume with the given altitude series. */
function runAltitudes(alts: number[], dtS = 4): { sev: string[]; reasons: string[] } {
  const engine = new ConflictEngine();
  const sev: string[] = [];
  const reasons: string[] = [];
  alts.forEach((alt, i) => {
    const ac = straightFlightSnapshot({ lat: 40.75, lon: -73.85, t: i * dtS, alt_ft: alt, gs_kt: 0, climb_fpm: 0 });
    const alerts = engine.tick([ac], [classBVolume()], ac.t);
    sev.push(alerts[0]?.severity ?? "none");
    reasons.push(alerts[0]?.reason ?? "");
  });
  return { sev, reasons };
}

describe("ConflictEngine: Class B floor trigger", () => {
  it("hands off when smoothed altitude is at or above floor - 100 inside the polygon", () => {
    const { sev, reasons } = runAltitudes([1480, 1490, 1470, 1485, 1480, 1475]);
    expect(sev.at(-1)).toBe("handoff");
    expect(reasons.at(-1)).toContain("At 1,480 ft inside Hudson Exclusion");
    expect(reasons.at(-1)).toContain("at or above Class B floor 1,300 − 100 ft without a recorded clearance");
  });

  it("does not hand off at 1,150 ft (below floor - 100), even with one noisy 1,250 ft sample", () => {
    const { sev } = runAltitudes([1150, 1150, 1150, 1150, 1150, 1250, 1150, 1150, 1150]);
    expect(sev).not.toContain("handoff");
  });

  it("does not extrapolate ADS-B jitter into a phantom climb (N84BL pattern)", () => {
    // Level near 600 ft with +/-100 ft jitter: two-point rates read thousands of fpm.
    const { sev } = runAltitudes([600, 700, 560, 690, 570, 700, 590, 680, 600]);
    expect(sev.every((s) => s === "none")).toBe(true);
  });

  it("issues a caution for a sustained climb that will reach floor - 100 within 90 s", () => {
    // 1,000 ft climbing 600 fpm (10 ft/s): reaches 1,200 ft in ~20 s.
    const alts = Array.from({ length: 8 }, (_, i) => 800 + i * 4 * 10);
    const { sev, reasons } = runAltitudes(alts);
    expect(sev.at(-1)).toBe("caution");
    expect(reasons.at(-1)).toContain("Class B floor 1,300 − 100 ft");
  });

  it("keeps the handoff alive across one dip below the threshold (hysteresis)", () => {
    const { sev } = runAltitudes([1500, 1500, 1500, 1500, 1500, 1100]);
    expect(sev.slice(-2)).toEqual(["handoff", "handoff"]);
  });
});

describe("ConflictEngine: one logical volume per runway final", () => {
  it("raises a single alert, naming the segment, when several segments could be entered", () => {
    const volumes = loadProtectedVolumes();
    const seg4 = volumes.find((v) => v.id === "lga22_final_seg4")!;
    const cx = seg4.ring.slice(0, 4).reduce((s, p) => s + p[0], 0) / 4;
    const cy = seg4.ring.slice(0, 4).reduce((s, p) => s + p[1], 0) / 4;
    // At seg4's centre, flying the final inbound (track 212) at 1,500 ft.
    const ac = straightFlightSnapshot({
      lat: cy,
      lon: cx,
      track_deg: 212,
      gs_kt: 90,
      alt_ft: 1500,
      track_history: [212, 212, 212],
    });
    const engine = new ConflictEngine();
    const alerts = engine.tick([ac], volumes, 0).filter((a) => a.volume_id.startsWith("lga22"));
    expect(alerts).toHaveLength(1);
    expect(alerts[0].severity).toBe("handoff");
    expect(alerts[0].reason).toMatch(/crosses LGA Rwy 22 final \d\.\d nm from threshold at [\d,]+ ft, inside the arrival glidepath band \(\d[\d,]*–[\d,]+ ft\) in \d+ s\./);
  });
});

describe("ConflictEngine: real Saturday traffic", () => {
  // One engine per aircraft, ticking on that aircraft's own `t`, so hysteresis and the
  // altitude history are never shared across aircraft or mixed across time bases.
  interface Row {
    reg: string;
    severity: "handoff" | "caution";
    volume_id: string;
    first_t: number;
    max_alt_in_polygon_ft: number;
  }

  function runSaturday() {
    const volumes = loadProtectedVolumes();
    const kindOf = new Map(volumes.map((v) => [v.id, v.kind]));
    const aircraft = loadReplay("saturday.json");
    const rows: Row[] = [];
    const nonClassBHandoffs: string[] = [];
    for (const a of aircraft) {
      const engine = new ConflictEngine();
      const worst = new Map<string, Row>();
      for (let i = 0; i < a.points.length; i++) {
        const snap = snapshotAt(a, i);
        const alerts = engine.tick([snap], volumes, snap.t);
        // at most one approach/departure alert per runway at any instant
        const runways = alerts
          .filter((x) => kindOf.get(x.volume_id) !== "class_b_floor")
          .map((x) => volumes.find((v) => v.id === x.volume_id)!.runway);
        expect(new Set(runways).size, `${a.reg} t=${snap.t}`).toBe(runways.length);
        for (const al of alerts) {
          if (al.severity !== "handoff" && al.severity !== "caution") continue;
          if (al.severity === "handoff" && kindOf.get(al.volume_id) !== "class_b_floor") {
            nonClassBHandoffs.push(`${a.reg} ${al.volume_id}: ${al.reason}`);
          }
          const prev = worst.get(al.id);
          if (!prev || (al.severity === "handoff" && prev.severity === "caution")) {
            const ring = volumes.find((v) => v.id === al.volume_id)!.ring;
            const alts = a.points.filter((p) => pointInRing(p.lat, p.lon, ring)).map((p) => p.alt_ft_msl);
            worst.set(al.id, {
              reg: a.reg,
              severity: al.severity,
              volume_id: al.volume_id,
              first_t: prev?.first_t ?? Math.round(snap.t),
              max_alt_in_polygon_ft: alts.length ? Math.round(Math.max(...alts)) : 0,
            });
          }
        }
      }
      rows.push(...worst.values());
    }
    return { rows, nonClassBHandoffs, total: aircraft.length, kindOf };
  }

  it("raises zero handoffs from approach or departure volumes", () => {
    const { nonClassBHandoffs } = runSaturday();
    expect(nonClassBHandoffs).toEqual([]);
  });

  it("logs and snapshots the Class B floor handoff/caution breakdown per aircraft", () => {
    const { rows, total, kindOf } = runSaturday();
    const summary = rows
      .filter((r) => kindOf.get(r.volume_id) === "class_b_floor")
      .map(({ reg, severity, first_t, max_alt_in_polygon_ft }) => ({ reg, severity, first_t, max_alt_in_polygon_ft }))
      .sort((a, b) => a.reg.localeCompare(b.reg) || a.severity.localeCompare(b.severity));
    // eslint-disable-next-line no-console
    console.log(
      `Class B floor: ${summary.filter((r) => r.severity === "handoff").length} handoff, ` +
        `${summary.filter((r) => r.severity === "caution").length} caution, of ${total} helicopters`,
      summary,
    );
    // Track B's Hudson polygon changes show up as a diff in this snapshot.
    expect(summary).toMatchSnapshot();
  });
});

