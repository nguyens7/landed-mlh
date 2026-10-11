// Scenario picker state: which S1-S6 is loaded, play / reset orchestration, scoreboard panel.
// Server calls go through voice/api.post; a failed server call never blocks the local replay.
import { create } from "zustand";
import type { ReplayAircraft, ReplayFile } from "../data/types";
import { useDeskStore } from "../store/useDeskStore";
import { post } from "../voice/api";
import { emptyVoice } from "../voice/reduce";
import { useVoiceStore } from "../voice/useVoiceStore";

export interface ScenarioInfo {
  id: string;
  title: string;
  window_s: number;
}

export interface ScoreRow {
  id: string;
  title: string;
  three_of_three: boolean;
  repeat: number;
  tally: { pass: number; fail: number; partial: number; pending: number; gap: number; total: number };
}

interface LinesFile {
  lines: { t: number }[];
}

interface ScenarioState {
  scenarios: ScenarioInfo[];
  scoreboard: ScoreRow[];
  selectedId: string;
  running: boolean;
  status: string;
  scoreboardOpen: boolean;
  init: () => Promise<void>;
  select: (id: string) => void;
  toggleScoreboard: () => void;
  play: () => Promise<void>;
  reset: () => Promise<void>;
}

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`failed to load ${path}: ${r.status}`);
  return (await r.json()) as T;
}

/** Local engine, alerts, decisions, proposal cards and the emergency lock all back to empty. */
export function clearLocalState(): void {
  useVoiceStore.setState({ ...emptyVoice, editingId: null, editError: null });
  if (typeof document !== "undefined") document.body.classList.remove("agent-locked");
}

/** Where the scripted clock starts: just before the first aircraft or line, whichever is first. */
export function scenarioStartT(aircraft: ReplayAircraft[], lines: { t: number }[]): number {
  const firsts = [...aircraft.map((a) => a.points[0]?.t ?? Infinity), ...lines.map((l) => l.t)];
  return Math.max(0, Math.min(...firsts) - 2);
}

export const useScenarioStore = create<ScenarioState>((set, get) => ({
  scenarios: [],
  scoreboard: [],
  selectedId: "S1",
  running: false,
  status: "",
  scoreboardOpen: false,

  init: async () => {
    try {
      const idx = await getJson<{ scenarios: ScenarioInfo[] }>("/data/scenarios/index.json");
      set({ scenarios: idx.scenarios });
    } catch {
      set({ status: "scenario list unavailable" });
    }
    try {
      const sb = await getJson<{ scenarios: ScoreRow[] }>("/data/scenarios/scoreboard.json");
      set({ scoreboard: sb.scenarios });
    } catch {
      // the scoreboard panel just stays empty
    }
  },

  select: (id) => set({ selectedId: id }),
  toggleScoreboard: () => set((s) => ({ scoreboardOpen: !s.scoreboardOpen })),

  // Load the tracks as simulated aircraft, clear everything, then start the server's scripted lines.
  play: async () => {
    const id = get().selectedId;
    set({ status: `loading ${id}`, running: false });
    try {
      const [tracks, lines] = await Promise.all([
        getJson<ReplayFile>(`/data/scenarios/${id}/tracks.json`),
        getJson<LinesFile>(`/data/scenarios/${id}/lines.json`),
      ]);
      const startT = scenarioStartT(tracks.aircraft, lines.lines);
      clearLocalState();
      useDeskStore.getState().setReplay({
        aircraft: tracks.aircraft,
        windowSeconds: Number(tracks.metadata.window_seconds ?? 300),
        scenarioId: id,
        startT,
      });
      await new Promise((r) => setTimeout(r, 400)); // let the bridge's roster / rewind posts land first
      let status = `${id} running`;
      try {
        await post(`/scenario/${id}/play`, { start_t: startT, speed: useDeskStore.getState().speed });
      } catch (e) {
        status = `${id} replay only: server ${e instanceof Error ? e.message : "unreachable"}`;
      }
      useDeskStore.getState().play();
      set({ running: true, status });
    } catch (e) {
      set({ status: e instanceof Error ? e.message : "load failed" });
    }
  },

  // Clear the desk, the proposals and the emergency lock, server and local; rewind the clock; stay paused.
  reset: async () => {
    useDeskStore.getState().pause();
    let status = "reset";
    try {
      await post("/scenario/reset");
    } catch (e) {
      status = `reset locally: server ${e instanceof Error ? e.message : "unreachable"}`;
    }
    clearLocalState();
    const d = useDeskStore.getState();
    const first = Object.values(d.aircraftByHex).map((a) => a.points[0]?.t ?? Infinity);
    d.seek(d.scenarioId ? Math.max(0, Math.min(...first) - 2) : 0);
    set({ running: false, status });
  },
}));
