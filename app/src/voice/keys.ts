import type { Proposal } from "./types";

/** A card's A/E/R keys do nothing until it has been on screen this long (SPEC 2.1). */
export const ARM_MS = 1000;

export type KeyAction =
  | { kind: "approve" | "edit" | "reject"; proposalId: string }
  | null;

/** The one card keys are bound to: it is the proposal currently shown as active. */
export interface ActiveCard {
  id: string;
  /** Local Date.now() when this card became the active card (arm delay starts here). */
  shownAt: number;
  /** Local Date.now() when it expires (never auto-sent). */
  expiresAt: number;
  status: Proposal["status"];
}

export function isArmed(card: Pick<ActiveCard, "shownAt">, now: number): boolean {
  return now - card.shownAt >= ARM_MS;
}

export function remainingMs(card: Pick<ActiveCard, "expiresAt">, now: number): number {
  return Math.max(0, card.expiresAt - now);
}

/** Map a key press to an action on the active card, or null. Pure so it can be unit tested.
 * A key never targets a card other than `active`, and nothing fires before the card is armed,
 * after it expired, while editing, or while locked (agent speech only). */
export function resolveKey(
  key: string,
  active: ActiveCard | null,
  now: number,
  opts: { editing: boolean; locked: boolean; kind: Proposal["kind"] },
): KeyAction {
  if (!active || opts.editing || active.status !== "pending") return null;
  if (!isArmed(active, now) || remainingMs(active, now) <= 0) return null;
  const k = key.toLowerCase();
  if (k === "a") return opts.locked && opts.kind === "speak" ? null : { kind: "approve", proposalId: active.id };
  if (k === "e") return opts.kind === "speak" ? { kind: "edit", proposalId: active.id } : null;
  if (k === "r") return { kind: "reject", proposalId: active.id };
  return null;
}
