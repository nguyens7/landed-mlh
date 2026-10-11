import type { ActiveCard } from "./keys";
import type { AuditEntry, Proposal, ServerEvent } from "./types";

export interface Entry {
  p: Proposal;
  /** Local Date.now() when this version of the proposal arrived. */
  receivedAt: number;
}

export interface VoiceData {
  entries: Record<string, Entry>;
  order: string[];
  audit: AuditEntry[];
  locked: boolean;
  activeId: string | null;
  /** Local Date.now() when the active card became active (arm delay starts here). */
  activeShownAt: number;
}

export const emptyVoice: VoiceData = {
  entries: {},
  order: [],
  audit: [],
  locked: false,
  activeId: null,
  activeShownAt: 0,
};

/** Local expiry: server clock skew is irrelevant because we only use the 10 s duration. */
export function localExpiry(e: Entry): number {
  const p = e.p;
  const dur = p.expires_at_ms !== null ? p.expires_at_ms - p.created_at_ms : 0;
  return e.receivedAt + dur;
}

/** The card the A/E/R keys are bound to: the newest proposal still pending and unexpired. */
export function pickActive(d: Pick<VoiceData, "entries" | "order">, now: number): string | null {
  for (let i = d.order.length - 1; i >= 0; i--) {
    const e = d.entries[d.order[i]];
    if (e && e.p.status === "pending" && localExpiry(e) > now) return e.p.id;
  }
  return null;
}

export function activeCard(d: VoiceData): ActiveCard | null {
  if (!d.activeId) return null;
  const e = d.entries[d.activeId];
  if (!e) return null;
  return { id: e.p.id, shownAt: d.activeShownAt, expiresAt: localExpiry(e), status: e.p.status };
}

function withActive(d: VoiceData, now: number): VoiceData {
  const activeId = pickActive(d, now);
  if (activeId === d.activeId) return d;
  // A different card became active: its arm delay restarts, so a key meant for the old card
  // can never fire the new one.
  return { ...d, activeId, activeShownAt: now };
}

/** An edited proposal keeps its id but is a fresh card: re-arm. */
function isRefresh(prev: Entry | undefined, next: Proposal): boolean {
  return !!prev && next.status === "pending" && prev.p.created_at_ms !== next.created_at_ms;
}

export function reduce(d: VoiceData, ev: ServerEvent, now: number): VoiceData {
  switch (ev.type) {
    case "snapshot": {
      const entries: Record<string, Entry> = {};
      for (const p of ev.proposals) entries[p.id] = { p, receivedAt: now };
      return withActive(
        { ...d, entries, order: ev.proposals.map((p) => p.id), audit: ev.audit, locked: ev.locked },
        now,
      );
    }
    case "proposal": {
      const prev = d.entries[ev.proposal.id];
      const order = prev ? d.order : [...d.order, ev.proposal.id];
      const receivedAt = prev && !isRefresh(prev, ev.proposal) ? prev.receivedAt : now;
      let next: VoiceData = { ...d, entries: { ...d.entries, [ev.proposal.id]: { p: ev.proposal, receivedAt } }, order };
      if (isRefresh(prev, ev.proposal) && d.activeId === ev.proposal.id) {
        next = { ...next, activeShownAt: now };
      }
      return withActive(next, now);
    }
    case "expired": {
      const e = d.entries[ev.id];
      if (!e) return d;
      return withActive({ ...d, entries: { ...d.entries, [ev.id]: { ...e, p: { ...e.p, status: "expired" } } } }, now);
    }
    case "lock":
      return { ...d, locked: ev.locked };
    case "audit":
      return { ...d, audit: [...d.audit, ev.entry].slice(-200) };
    default:
      return d;
  }
}

/** Replay seek / Jump-to-conflict: every pending card is dropped locally (the server drops them too). */
export function dropPending(d: VoiceData, now: number): VoiceData {
  const entries: Record<string, Entry> = {};
  for (const [id, e] of Object.entries(d.entries)) {
    entries[id] = e.p.status === "pending" ? { ...e, p: { ...e.p, status: "expired" } } : e;
  }
  return withActive({ ...d, entries }, now);
}
