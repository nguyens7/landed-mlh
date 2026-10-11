// Glue between the scenario player, the voice bridge and the radio queue.
// Pilot clips come from GET /scenario/{id}/audio/{line}; a 404 (audio not built) just means the row shows silently.
import { SERVER } from "../voice/api";
import { playBuffer, playProposal, squelch, stopAudio } from "../voice/audio";
import { useVoiceStore } from "../voice/useVoiceStore";
import { configureRadio, enqueue, resetRadio } from "./radio";
import type { RadioItem } from "./radio";

configureRadio({ squelch }, stopAudio);

export interface TimedLine {
  id: string;
  aircraft: string;
  in_s: number;
  audio_url: string | null;
}

const clips = new Map<string, Promise<ArrayBuffer | null>>();
let timers: number[] = [];

function fetchClip(url: string): Promise<ArrayBuffer | null> {
  let p = clips.get(url);
  if (!p) {
    p = fetch(`${SERVER}${url}`)
      .then((r) => (r.ok ? r.arrayBuffer() : null))
      .catch(() => null);
    clips.set(url, p);
  }
  return p;
}

export function pilotItem(sid: string, lineId: string, reg: string, text: string, audioUrl: string | null): RadioItem {
  return {
    id: `pilot:${sid}:${lineId}:${Date.now()}`,
    speaker: "pilot",
    label: `PILOT · ${reg}`,
    text,
    play: async () => {
      if (!audioUrl) return false;
      const data = await fetchClip(audioUrl);
      return data ? playBuffer(data.slice(0), false) : false;
    },
  };
}

export function landedItem(proposalId: string, text: string): RadioItem {
  return {
    id: `landed:${proposalId}`,
    speaker: "landed",
    label: "LANDED",
    text,
    play: () => playProposal(proposalId),
  };
}

/** Landed's spoken reply to the radio (called by the voice bridge for every audible proposal). */
export function enqueueLanded(proposalId: string, text: string): void {
  enqueue(landedItem(proposalId, text));
}

export function cancelSchedule(): void {
  for (const t of timers) window.clearTimeout(t);
  timers = [];
}

/** Drop pending pilot timers, the queue and the transcript (new play, reset). */
export function resetScenarioRadio(): void {
  cancelSchedule();
  resetRadio();
}

/** Queue each pilot line of a playing scenario at its scripted wall time. Landed's answer to each line is
 * delayed by the server until the pilot's clip is over, and the queue keeps the two from overlapping. */
export function scheduleScenarioRadio(sid: string, timed: TimedLine[], texts: Record<string, string>): void {
  resetScenarioRadio();
  for (const ln of timed) {
    const text = texts[ln.id];
    if (!text) continue;
    if (ln.audio_url) void fetchClip(ln.audio_url); // warm the clip so it starts on time
    timers.push(
      window.setTimeout(() => enqueue(pilotItem(sid, ln.id, ln.aircraft, text, ln.audio_url)), Math.max(0, ln.in_s) * 1000),
    );
  }
}

/** S2 L1, kept inline so the pilot is queued synchronously on Jump (before any proposal can arrive).
 * A test checks this against app/public/data/scenarios/S2/lines.json. */
export const JUMP_PILOT = {
  scenario: "S2",
  line: "L1",
  reg: "N312LM",
  text: "Landed desk, MEDEVAC Three One Two Lima, East 34th, request direct College Point area, six hundred.",
};

/** Jump to conflict: the medevac's scripted call (S2 L1) goes out first; Landed's "standby" follows from the
 * engine's handoff proposal, which the bridge queues behind it. Silent no-op without a server. */
export function startJumpExchange(): void {
  if (!useVoiceStore.getState().connected) return;
  resetScenarioRadio();
  const j = JUMP_PILOT;
  enqueue(pilotItem(j.scenario, j.line, j.reg, j.text, `/scenario/${j.scenario}/audio/${j.line}`));
}
