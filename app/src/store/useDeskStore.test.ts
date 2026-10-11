import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConflictEngine } from "../engine/conflictEngine";
import { loadProtectedVolumes, loadReplay, snapshotAt } from "../engine/testFixtures";
import type { ReplayAircraft } from "../data/types";
import { interpolateAircraft } from "../data/interpolate";
import { MAX_FRAME_DT_MS, useDeskStore } from "./useDeskStore";
import { pickProminentAlert } from "./prominentAlert";

const SIM_HEX = "SIM312LM";

function loadStore(): void {
  const aircraft = [...loadReplay("saturday.json"), ...loadReplay("sim_medevac.json")] as ReplayAircraft[];
  const aircraftByHex: Record<string, ReplayAircraft> = {};
  for (const ac of aircraft) aircraftByHex[ac.hex] = ac;
  useDeskStore.setState({
    loaded: true,
    windowSeconds: 900,
    aircraftByHex,
    volumes: loadProtectedVolumes(),
    conflictEntryT: 450,
    playing: false,
    speed: 4,
    currentT: 0,
    snapshots: [],
    alerts: [],
    alertLog: [],
    decisions: [],
    dismissedAlertId: null,
  });
  useDeskStore.getState().seek(0);
}

/** One simulated second per call (250 ms of real time at 4x). */
function stepOneSecond(): void {
  vi.advanceTimersByTime(1000);
  useDeskStore.getState().advance(250);
}

function simAlert() {
  return useDeskStore.getState().alerts.find((a) => a.aircraft.hex === SIM_HEX);
}

function playUntil(pred: () => boolean, maxSteps = 400): void {
  for (let i = 0; i < maxSteps && !pred(); i++) stepOneSecond();
  expect(pred()).toBe(true);
}

describe("one alert per aircraft (finding 1)", () => {
  it("collapses the Rwy 22 final and the Rwy 4/13 departure volumes into one medevac alert", () => {
    const [medevac] = loadReplay("sim_medevac.json");
    const volumes = loadProtectedVolumes();
    // all runways active, so the Rwy 4 departure corridor overlaps the Rwy 22 final
    const engine = new ConflictEngine({ arrivals: ["22", "31"], departures: ["4", "13"] });
    let sawHandoff = false;
    let sawAlso = false;
    for (let i = 0; i < medevac.points.length; i++) {
      const snap = snapshotAt(medevac, i);
      const alerts = engine.tick([snap], volumes, snap.t);
      expect(alerts.filter((a) => a.aircraft.hex === SIM_HEX).length).toBeLessThanOrEqual(1);
      const a = alerts[0];
      if (a?.severity === "handoff") {
        sawHandoff = true;
        // approach wins ties over departure
        expect(volumes.find((v) => v.id === a.volume_id)?.kind).toBe("approach");
        if (a.also_volumes?.length) {
          sawAlso = true;
          expect(a.reason).toContain("Also overlaps");
        }
      }
    }
    expect(sawHandoff).toBe(true);
    expect(sawAlso).toBe(true);
  });
});

describe("alert log and latency (finding 2)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-10T15:00:00Z"));
    loadStore();
  });
  afterEach(() => vi.useRealTimers());

  it("updates the log row in place on escalation and times latency from the handoff", () => {
    useDeskStore.getState().seek(300);
    useDeskStore.setState({ playing: true });
    // the row exists (possibly as advisory/caution) and must follow the live alert
    playUntil(() => simAlert()?.severity === "handoff");
    const handoffAt = Date.now();

    const rows = useDeskStore.getState().alertLog.filter((r) => r.aircraft.hex === SIM_HEX);
    expect(rows).toHaveLength(1);
    expect(rows[0].severity).toBe("handoff");
    expect(rows[0].confidence).toBe(simAlert()!.confidence);

    stepOneSecond();
    stepOneSecond();
    stepOneSecond();
    useDeskStore.getState().acknowledge(simAlert()!.id);
    const [decision] = useDeskStore.getState().decisions;
    expect(decision.latency_ms).toBe(Date.now() - handoffAt);
    expect(decision.latency_ms).toBe(3000);
  });

  it("counts the handoff countdown down smoothly, about one second per second", () => {
    useDeskStore.getState().seek(380);
    useDeskStore.setState({ playing: true });
    playUntil(() => simAlert()?.severity === "handoff");
    const ttes: number[] = [];
    for (let i = 0; i < 12; i++) {
      stepOneSecond();
      const a = simAlert();
      if (a?.severity === "handoff") ttes.push(a.time_to_entry_s);
    }
    expect(ttes.length).toBeGreaterThan(6);
    for (let i = 1; i < ttes.length; i++) {
      const d = ttes[i - 1] - ttes[i];
      if (ttes[i] > 0) expect(d).toBeGreaterThan(0.5);
      expect(d).toBeLessThan(1.6);
    }
  });
});

describe("seek resets state (finding 3)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-10T15:00:00Z"));
    loadStore();
  });
  afterEach(() => vi.useRealTimers());

  it("shows the card every time: Jump to conflict, scrub back, Jump to conflict again", () => {
    for (let run = 0; run < 3; run++) {
      useDeskStore.getState().jumpToConflict();
      expect(useDeskStore.getState().alerts.find((a) => a.severity === "handoff")?.aircraft.hex).not.toBe(SIM_HEX);
      playUntil(() => pickProminentAlert(useDeskStore.getState().alerts, useDeskStore.getState().volumes)?.aircraft.hex === SIM_HEX);
      const card = pickProminentAlert(useDeskStore.getState().alerts, useDeskStore.getState().volumes)!;
      expect(useDeskStore.getState().dismissedAlertId).not.toBe(card.id);

      // controller takes over (card dismissed), then scrubs back to the start
      useDeskStore.getState().takeOver(card.id);
      useDeskStore.getState().dismissAlert(card.id);
      useDeskStore.getState().seek(10);
      const s = useDeskStore.getState();
      expect(s.dismissedAlertId).toBeNull();
      expect(s.decisions).toEqual([]);
      expect(s.alertLog.find((r) => r.aircraft.hex === SIM_HEX)).toBeUndefined();
      expect(pickProminentAlert(s.alerts, s.volumes)?.aircraft.hex).not.toBe(SIM_HEX);
    }
  });

  it("holds no stale handoff after seeking backwards (no negative dt)", () => {
    const volumes = loadProtectedVolumes();
    const [medevac] = loadReplay("sim_medevac.json");
    const engine = new ConflictEngine();
    let lastHandoffI = -1;
    for (let i = 0; i < medevac.points.length; i++) {
      const snap = snapshotAt(medevac, i);
      if (engine.tick([snap], volumes, snap.t).some((a) => a.severity === "handoff")) lastHandoffI = i;
    }
    expect(lastHandoffI).toBeGreaterThan(0);
    // jump back to before the aircraft was anywhere near the volumes
    const early = snapshotAt(medevac, 2);
    const alerts = engine.tick([early], volumes, early.t);
    expect(alerts.filter((a) => a.severity === "handoff")).toEqual([]);

    // and through the store
    useDeskStore.getState().seek(445);
    useDeskStore.getState().seek(100);
    expect(useDeskStore.getState().alerts.filter((a) => a.severity === "handoff" && a.aircraft.hex === SIM_HEX)).toEqual([]);
  });
});

describe("frame delta clamp (finding 7)", () => {
  beforeEach(() => loadStore());

  it("advances at most MAX_FRAME_DT_MS of real time per frame, even at 16x", () => {
    useDeskStore.setState({ playing: true, speed: 16 });
    useDeskStore.getState().seek(100);
    useDeskStore.setState({ playing: true });
    useDeskStore.getState().advance(60_000); // a resumed background tab
    expect(useDeskStore.getState().currentT).toBeCloseTo(100 + (MAX_FRAME_DT_MS / 1000) * 16, 5);
  });

  it("ignores negative deltas", () => {
    useDeskStore.getState().seek(100);
    useDeskStore.setState({ playing: true });
    useDeskStore.getState().advance(-500);
    expect(useDeskStore.getState().currentT).toBe(100);
  });
});

describe("interpolation gaps (finding 5)", () => {
  const pt = (t: number, lon: number) => ({ t, lat: 40.7, lon, alt_ft_msl: 500, gs_kt: 60, track_deg: 90 });
  const ac = (points: ReturnType<typeof pt>[]): ReplayAircraft => ({
    hex: "GAP001",
    reg: "N1GAP",
    role_guess: "other",
    simulated: false,
    points,
  });

  it("returns null (not evaluated) when the bracketing gap is over 30 s", () => {
    const a = ac([pt(0, -73.9), pt(10, -73.88), pt(100, -73.8)]);
    expect(interpolateAircraft(a, 50)).toBeNull();
    expect(interpolateAircraft(a, 5)).not.toBeNull();
  });

  it("still interpolates normal gaps", () => {
    const a = ac([pt(0, -73.9), pt(20, -73.8)]);
    const s = interpolateAircraft(a, 10)!;
    expect(s.lon).toBeCloseTo(-73.85, 6);
    expect(s.gs_kt).toBe(60);
  });

  it("the replay has no null gs/track points", () => {
    for (const a of loadReplay("saturday.json"))
      for (const p of a.points) {
        expect(p.gs_kt, `${a.reg} t=${p.t}`).not.toBeNull();
        expect(p.track_deg, `${a.reg} t=${p.t}`).not.toBeNull();
      }
  });
});
