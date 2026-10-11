import { create } from "zustand";
import { ConflictEngine } from "../engine/conflictEngine";
import type { Alert, AircraftSnapshot, ProtectedVolume } from "../engine/types";
import { loadFixedWing, loadGeoData, loadReplayData } from "../data/loadData";
import { interpolateAircraft } from "../data/interpolate";
import type { GeoFeatureCollection, ReplayAircraft } from "../data/types";

export type Speed = 1 | 4 | 16;

export interface Decision {
  alertId: string;
  reg: string;
  decision: "acknowledge" | "take_over";
  at_iso: string;
  latency_ms: number;
}

interface DeskState {
  loaded: boolean;
  error: string | null;
  windowSeconds: number;
  aircraftByHex: Record<string, ReplayAircraft>;
  /** Display-only airliners (map layer). Deliberately NOT in aircraftByHex: never reaches the engine. */
  fixedWingByHex: Record<string, ReplayAircraft>;
  volumes: ProtectedVolume[];
  corridors: GeoFeatureCollection | null;
  protectedVolumesGeo: GeoFeatureCollection | null;
  approachPaths: GeoFeatureCollection | null;
  referencePoints: GeoFeatureCollection | null;

  currentT: number;
  playing: boolean;
  speed: Speed;

  snapshots: AircraftSnapshot[];
  alerts: Alert[];
  alertLog: Alert[];
  decisions: Decision[];

  conflictEntryT: number | null; // precomputed: when the sim medevac first enters a volume
  /** Alert whose card the controller dismissed; cleared on every seek. */
  dismissedAlertId: string | null;
  /** Aircraft the hero card is about; the map rings it and dims the rest. null = default to the
   * top-ranked handoff (the AlertCard alert). */
  focusedHex: string | null;
  /** Incremented on every seek so views can drop derived state (trails). */
  seekEpoch: number;

  /** Scenario id (S1..S6) whose scripted tracks replace the Saturday replay; null = Saturday replay. */
  scenarioId: string | null;

  load: () => Promise<void>;
  /** Swap in a scenario's tracks (or the Saturday replay again via load()), reset the engine, seek to startT. */
  setReplay: (r: { aircraft: ReplayAircraft[]; windowSeconds: number; scenarioId: string; startT: number }) => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: Speed) => void;
  seek: (t: number) => void;
  advance: (realDtMs: number) => void;
  jumpToConflict: () => void;
  acknowledge: (alertId: string) => void;
  takeOver: (alertId: string) => void;
  dismissAlert: (alertId: string) => void;
  setFocusedHex: (hex: string | null) => void;
}

/** Cap on the real-time delta one frame may advance the replay by, so a resumed background
 * tab (rAF paused for seconds) at 16x cannot skip past the conflict. */
export const MAX_FRAME_DT_MS = 250;

/** How far before a seek target the engine is replayed (in sim seconds, at this step) so its
 * track history is warm when the target time is shown. */
const SEEK_WARMUP_S = 30;
const SEEK_WARMUP_STEP_S = 2;
/** Jump lands this many sim seconds before entry: just after the medevac handoff fires, so its
 * card is the one on screen. */
const JUMP_LEAD_S = 55;

const engine = new ConflictEngine();
// alert id -> Date.now() when its severity first became "handoff", for decision latency
const surfacedAtReal = new Map<string, number>();

/** Fold this tick's alerts into the log: new ids are appended, existing rows are updated in
 * place (severity, confidence, reason, ...), keeping the row's original first_seen_t. */
function mergeAlertLog(log: Alert[], alerts: Alert[]): Alert[] {
  let next = log;
  for (const a of alerts) {
    const i = next.findIndex((r) => r.id === a.id);
    if (i === -1) {
      next = [...next, a];
    } else {
      const row = next[i];
      if (
        row.severity !== a.severity ||
        row.confidence !== a.confidence ||
        row.reason !== a.reason ||
        row.volume_id !== a.volume_id
      ) {
        next = next === log ? [...log] : next;
        next[i] = { ...a, first_seen_t: row.first_seen_t };
      }
    }
  }
  return next;
}

export const useDeskStore = create<DeskState>((set, get) => ({
  loaded: false,
  error: null,
  windowSeconds: 900,
  aircraftByHex: {},
  fixedWingByHex: {},
  volumes: [],
  corridors: null,
  protectedVolumesGeo: null,
  approachPaths: null,
  referencePoints: null,

  currentT: 0,
  playing: false,
  speed: 1,

  snapshots: [],
  alerts: [],
  alertLog: [],
  decisions: [],
  conflictEntryT: null,
  dismissedAlertId: null,
  focusedHex: null,
  setFocusedHex: (hex) => {
    if (get().focusedHex !== hex) set({ focusedHex: hex });
  },
  seekEpoch: 0,
  scenarioId: null,

  setReplay: ({ aircraft, windowSeconds, scenarioId, startT }) => {
    const aircraftByHex: Record<string, ReplayAircraft> = {};
    for (const ac of aircraft) aircraftByHex[ac.hex] = ac;
    engine.reset();
    surfacedAtReal.clear();
    set({
      aircraftByHex,
      windowSeconds,
      scenarioId,
      playing: false,
      conflictEntryT: findFirstSimEntry(aircraft, get().volumes),
    });
    get().seek(startT);
  },

  load: async () => {
    try {
      const [{ aircraft, windowSeconds }, geo, fixedWing] = await Promise.all([
        loadReplayData(),
        loadGeoData(),
        loadFixedWing(),
      ]);
      const fixedWingByHex: Record<string, ReplayAircraft> = {};
      for (const ac of fixedWing) fixedWingByHex[ac.hex] = ac;
      const aircraftByHex: Record<string, ReplayAircraft> = {};
      for (const ac of aircraft) aircraftByHex[ac.hex] = ac;

      const conflictEntryT = findFirstSimEntry(aircraft, geo.volumes);

      engine.reset();
      surfacedAtReal.clear();

      set({
        loaded: true,
        windowSeconds,
        aircraftByHex,
        fixedWingByHex,
        volumes: geo.volumes,
        corridors: geo.corridors,
        protectedVolumesGeo: geo.protectedVolumes,
        approachPaths: geo.approachPaths,
        referencePoints: geo.referencePoints,
        conflictEntryT,
        scenarioId: null,
        playing: false,
        currentT: 0,
        snapshots: [],
        alerts: [],
        alertLog: [],
        decisions: [],
      });
      get().seek(0);
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
    }
  },

  play: () => set({ playing: true }),
  pause: () => set({ playing: false }),
  setSpeed: (s) => set({ speed: s }),

  // A seek is a discontinuity: drop engine state, seen ids, the log and decisions, the
  // dismissed card and the projection cone (derived from alerts), then evaluate at t.
  seek: (t) => {
    engine.reset();
    surfacedAtReal.clear();
    set((s) => ({
      alerts: [],
      alertLog: [],
      decisions: [],
      dismissedAlertId: null,
      seekEpoch: s.seekEpoch + 1,
    }));
    // Warm the engine through the preceding seconds so track-history terms (vertical-rate fit,
    // heading stability) are populated and alerts already active at t show up immediately.
    for (let w = Math.max(0, t - SEEK_WARMUP_S); w < t; w += SEEK_WARMUP_STEP_S) tickTo(w);
    tickTo(t);
  },

  advance: (realDtMs) => {
    const { playing, speed, currentT, windowSeconds } = get();
    if (!playing) return;
    const dtMs = Math.min(MAX_FRAME_DT_MS, Math.max(0, realDtMs));
    const next = currentT + (dtMs / 1000) * speed;
    if (next >= windowSeconds) {
      set({ playing: false });
      tickTo(windowSeconds);
      return;
    }
    tickTo(next);
  },

  jumpToConflict: () => {
    const { conflictEntryT } = get();
    if (conflictEntryT === null) return;
    get().seek(Math.max(0, conflictEntryT - JUMP_LEAD_S));
    set({ playing: true });
  },

  acknowledge: (alertId) => {
    const entry = buildDecision(get(), alertId, "acknowledge");
    if (entry) set({ decisions: [...get().decisions, entry] });
  },
  takeOver: (alertId) => {
    const entry = buildDecision(get(), alertId, "take_over");
    if (entry) set({ decisions: [...get().decisions, entry] });
  },
  dismissAlert: (alertId) => set({ dismissedAlertId: alertId }),
}));

/** Evaluate the engine at sim time t (clamped) without resetting it: the continuous-playback
 * path used by `advance`. `seek` resets first, then calls this. */
function tickTo(t: number): void {
  const { aircraftByHex, volumes, windowSeconds, alertLog } = useDeskStore.getState();
  const clamped = Math.max(0, Math.min(windowSeconds, t));
  const snapshots = Object.values(aircraftByHex)
    .map((ac) => interpolateAircraft(ac, clamped))
    .filter((s): s is AircraftSnapshot => s !== null);
  const alerts = engine.tick(snapshots, volumes, clamped);

  // Decision latency runs from the moment an alert's severity first becomes "handoff".
  const live = new Set(alerts.map((a) => a.id));
  for (const id of surfacedAtReal.keys()) if (!live.has(id)) surfacedAtReal.delete(id);
  for (const a of alerts) {
    if (a.severity !== "handoff") surfacedAtReal.delete(a.id);
    else if (!surfacedAtReal.has(a.id)) surfacedAtReal.set(a.id, Date.now());
  }

  useDeskStore.setState({
    currentT: clamped,
    snapshots,
    alerts,
    alertLog: mergeAlertLog(alertLog, alerts),
  });
}

function buildDecision(state: DeskState, alertId: string, decision: Decision["decision"]): Decision | null {
  const alert = state.alertLog.find((a) => a.id === alertId) ?? state.alerts.find((a) => a.id === alertId);
  if (!alert) return null;
  const surfacedAt = surfacedAtReal.get(alertId) ?? Date.now();
  return {
    alertId,
    reg: alert.aircraft.reg,
    decision,
    at_iso: new Date().toISOString(),
    latency_ms: Date.now() - surfacedAt,
  };
}

/** Precompute when the simulated medevac first actually penetrates any protected volume,
 * from the raw replay points (ground truth, not the engine's projection) -- used only to
 * drive the "jump to conflict" demo button. */
function findFirstSimEntry(aircraft: ReplayAircraft[], volumes: ProtectedVolume[]): number | null {
  const sim = aircraft.find((a) => a.simulated);
  if (!sim) return null;
  for (const p of sim.points) {
    for (const v of volumes) {
      if (p.alt_ft_msl < v.floor_ft_msl || p.alt_ft_msl > v.ceiling_ft_msl) continue;
      if (pointInRing(p.lat, p.lon, v.ring)) return p.t;
    }
  }
  return null;
}

function pointInRing(lat: number, lon: number, ring: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersects = yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}
