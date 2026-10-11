import { useEffect } from "react";
import { useDeskStore } from "../store/useDeskStore";
import { ApiError, decide, post, wsUrl } from "./api";
import { enqueueLanded } from "../radio/scenarioRadio";
import { activeCard } from "./reduce";
import { resolveKey } from "./keys";
import { useVoiceStore } from "./useVoiceStore";
import type { ServerEvent } from "./types";

const played = new Set<string>();
const handedOff = new Set<string>(); // regs Landed has handed to the controller; it stops auto-talking to them
let needRoster = false; // set on (re)connect; the next store update re-posts the roster

// Server calls that depend on order (rewind, then the alert set) go through one chain.
let chain: Promise<unknown> = Promise.resolve();
function enqueue(fn: () => Promise<unknown>): void {
  chain = chain.then(fn).catch(() => undefined);
}

/** Mounts the live link to server/: WebSocket in, engine alerts out, keyboard A/E/R, audio playback. */
export function useVoiceBridge(): void {
  // WebSocket with reconnect
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        needRoster = true;
        useVoiceStore.getState().setConnected(true);
      };
      ws.onclose = () => {
        useVoiceStore.getState().setConnected(false);
        if (!closed) timer = window.setTimeout(connect, 1500);
      };
      ws.onmessage = (m) => {
        const ev = JSON.parse(m.data as string) as ServerEvent;
        if (ev.type === "snapshot") {
          for (const p of ev.proposals) played.add(p.id); // never replay old audio
          handedOff.clear();
        }
        useVoiceStore.getState().apply(ev);
        if (ev.type === "proposal") {
          const p = ev.proposal;
          maybePlay(p.id, p.status, p.audio_ready, p.spoken_text_preview, p.reg);
        }
      };
    };
    connect();
    const ticker = window.setInterval(() => useVoiceStore.getState().tick(), 100);
    return () => {
      closed = true;
      window.clearTimeout(timer);
      window.clearInterval(ticker);
      ws?.close();
    };
  }, []);

  // Roster, then engine handoff alerts for medevac aircraft -> POST /alerts
  useEffect(() => {
    let lastKey = "";
    let lastEpoch = useDeskStore.getState().seekEpoch;
    let rosterKey = "";
    const unsub = useDeskStore.subscribe((s) => {
      const medevac = Object.values(s.aircraftByHex).filter((a) => a.simulated || a.role_guess === "medevac");
      const regs = medevac.map((a) => a.reg);
      // Re-announce the roster on change and on every seek / reconnect (a server restart or /reset forgets it).
      if (regs.length && (regs.join() !== rosterKey || s.seekEpoch !== lastEpoch || needRoster)) {
        rosterKey = regs.join();
        needRoster = false;
        enqueue(() => post("/desk", { roster: regs, merge: true }));
      }
      const hexes = new Set(medevac.map((a) => a.hex));
      const relevant = s.alerts.filter((a) => hexes.has(a.aircraft.hex));
      const key = relevant.map((a) => `${a.id}:${a.severity}`).join("|");
      const send = () => enqueue(() => post("/alerts", relevant));
      if (s.seekEpoch !== lastEpoch) {
        // A seek / Jump-to-conflict: drop pending cards, then re-send the alert set so a repeat run fires again.
        lastEpoch = s.seekEpoch;
        lastKey = key;
        useVoiceStore.getState().rewind();
        enqueue(() => post("/rewind"));
        send();
      } else if (key !== lastKey) {
        lastKey = key;
        send();
      }
    });
    return unsub;
  }, []);

  // Keyboard: A / E / R bound to the single active card, only after the 1 s arm delay
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
      const v = useVoiceStore.getState();
      const card = activeCard(v);
      const kind = card ? v.entries[card.id].p.kind : "speak";
      const action = resolveKey(e.key, card, Date.now(), { editing: v.editingId !== null, locked: v.locked, kind });
      if (!action) return;
      e.preventDefault();
      runAction(action.kind, action.proposalId);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function runAction(kind: "approve" | "edit" | "reject", proposalId: string): void {
  const v = useVoiceStore.getState();
  if (kind === "edit") {
    v.setEditing(proposalId);
    return;
  }
  decide(proposalId, kind).catch((err: unknown) => {
    if (err instanceof ApiError) v.setEditError(`${kind}: ${err.message}`);
  });
}

/** True while the conflict engine has a handoff alert on this aircraft: the controller owns it, so routine
 * replies to it stay off the air. */
function inHandoff(reg: string): boolean {
  return useDeskStore.getState().alerts.some((a) => a.severity === "handoff" && a.aircraft.reg === reg);
}

/** Every cleared proposal goes on the radio queue, so Landed never talks over a pilot. Once Landed has told a
 * pilot "standby, controller will be with you", it stays quiet to that aircraft unless the controller approves. */
function maybePlay(id: string, status: string, audioReady: boolean, text: string, reg: string | null): void {
  if (!audioReady || played.has(id)) return;
  if (status !== "auto_spoken" && status !== "handoff_spoken" && status !== "approved") return;
  played.add(id);
  if (status === "auto_spoken" && reg && (handedOff.has(reg) || inHandoff(reg))) return;
  if (status === "handoff_spoken" && reg) handedOff.add(reg);
  enqueueLanded(id, text);
}
