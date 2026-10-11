// The two-way radio: one queue for every transmission, pilot and Landed, so they never overlap.
// Each item gets a transcript row when it starts, a squelch click on each end, and its audio (when sound is on
// and the clip exists). With no audio the row still appears and holds for roughly the time it takes to say it.
import { create } from "zustand";

export type Speaker = "pilot" | "landed";

export interface RadioRow {
  id: string;
  speaker: Speaker;
  label: string; // "PILOT · N312LM" or "LANDED"
  text: string;
  speaking: boolean;
}

export interface RadioItem {
  id: string;
  speaker: Speaker;
  label: string;
  text: string;
  /** Plays the audio; resolves true when it played to the end, false when there is nothing to hear. */
  play: () => Promise<boolean>;
}

export interface RadioDeps {
  squelch: () => Promise<void>;
  sleep: (ms: number) => Promise<void>;
}

export interface RadioLogEntry {
  event: "start" | "end";
  id: string;
  speaker: Speaker;
  heard: boolean;
  at: number;
}

interface RadioState {
  rows: RadioRow[];
  log: RadioLogEntry[];
  /** Replace the transcript (new play / reset). */
  clearRows: () => void;
}

const MAX_ROWS = 12;

export const useRadioStore = create<RadioState>((set) => ({
  rows: [],
  log: [],
  clearRows: () => set({ rows: [] }),
}));

let deps: RadioDeps = {
  squelch: () => Promise.resolve(),
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
};
let queue: RadioItem[] = [];
let running = false;
let generation = 0;
let onCancel: () => void = () => undefined;

/** Tests and the browser wire the real squelch / timers here. */
export function configureRadio(next: Partial<RadioDeps>, cancelHook?: () => void): void {
  deps = { ...deps, ...next };
  if (cancelHook) onCancel = cancelHook;
}

/** How long a line holds the channel when there is no audio to wait for. */
export function spokenMs(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1500, Math.min(9000, words * 380));
}

function note(entry: Omit<RadioLogEntry, "at">): void {
  const e = { ...entry, at: Date.now() };
  useRadioStore.setState((s) => ({ log: [...s.log, e].slice(-200) }));
  if (typeof window !== "undefined") {
    const w = window as unknown as { __radioLog?: RadioLogEntry[] };
    (w.__radioLog ??= []).push(e);
  }
}

function setRow(id: string, patch: Partial<RadioRow>): void {
  useRadioStore.setState((s) => ({ rows: s.rows.map((r) => (r.id === id ? { ...r, ...patch } : r)) }));
}

async function drain(): Promise<void> {
  if (running) return;
  running = true;
  const gen = generation;
  try {
    while (queue.length && gen === generation) {
      const item = queue.shift() as RadioItem;
      useRadioStore.setState((s) => ({
        rows: [
          ...s.rows.map((r) => ({ ...r, speaking: false })),
          { id: item.id, speaker: item.speaker, label: item.label, text: item.text, speaking: true },
        ].slice(-MAX_ROWS),
      }));
      await deps.squelch();
      note({ event: "start", id: item.id, speaker: item.speaker, heard: false });
      let heard = false;
      try {
        heard = await item.play();
      } catch {
        heard = false;
      }
      if (!heard) await deps.sleep(spokenMs(item.text));
      if (gen !== generation) break;
      await deps.squelch();
      note({ event: "end", id: item.id, speaker: item.speaker, heard });
      setRow(item.id, { speaking: false });
    }
  } finally {
    if (gen === generation) running = false;
  }
}

/** Add one transmission to the end of the queue. */
export function enqueue(item: RadioItem): void {
  queue.push(item);
  void drain();
}

/** Drop everything queued, stop what is playing, and let a new exchange start clean. */
export function cancelRadio(): void {
  queue = [];
  generation++;
  running = false;
  onCancel();
  useRadioStore.setState((s) => ({ rows: s.rows.map((r) => ({ ...r, speaking: false })) }));
}

export function resetRadio(): void {
  cancelRadio();
  useRadioStore.setState({ rows: [], log: [] });
  if (typeof window !== "undefined") (window as unknown as { __radioLog?: unknown[] }).__radioLog = [];
}
