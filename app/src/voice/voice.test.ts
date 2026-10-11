import { describe, expect, it } from "vitest";
import { ARM_MS, resolveKey } from "./keys";
import type { ActiveCard } from "./keys";
import { activeCard, dropPending, emptyVoice, reduce } from "./reduce";
import type { Proposal } from "./types";

function proposal(over: Partial<Proposal> = {}): Proposal {
  return {
    id: "p1",
    kind: "speak",
    tier: "approval",
    status: "pending",
    reg: "N2646X",
    template_id: "REPORT_ACK",
    slots: { reg: "N2646X" },
    spoken_text_preview: "MEDEVAC Two Six Four Six X-Ray, roger",
    confidence: 0.7,
    confidence_parts: {},
    reason: "",
    evidence: [],
    triggers: [],
    heard: "",
    created_at_ms: 1000,
    expires_at_ms: 11_000,
    audio_ready: true,
    latency_ms: null,
    source: "gemini",
    ...over,
  };
}

const opts = { editing: false, locked: false, kind: "speak" as const };
const card = (shownAt: number, expiresAt = shownAt + 10_000): ActiveCard => ({
  id: "p1",
  shownAt,
  expiresAt,
  status: "pending",
});

describe("A/E/R keys", () => {
  it("do nothing before the 1 s arm delay", () => {
    expect(resolveKey("a", card(0), ARM_MS - 1, opts)).toBeNull();
    expect(resolveKey("a", card(0), ARM_MS, opts)).toEqual({ kind: "approve", proposalId: "p1" });
  });
  it("map one key to one action on the active card", () => {
    expect(resolveKey("A", card(0), 2000, opts)).toEqual({ kind: "approve", proposalId: "p1" });
    expect(resolveKey("e", card(0), 2000, opts)).toEqual({ kind: "edit", proposalId: "p1" });
    expect(resolveKey("r", card(0), 2000, opts)).toEqual({ kind: "reject", proposalId: "p1" });
    expect(resolveKey("d", card(0), 2000, opts)).toBeNull();
    expect(resolveKey("a", null, 2000, opts)).toBeNull();
  });
  it("do nothing after expiry, while editing, or for approve while locked", () => {
    expect(resolveKey("a", card(0, 5000), 5000, opts)).toBeNull();
    expect(resolveKey("a", card(0), 2000, { ...opts, editing: true })).toBeNull();
    expect(resolveKey("a", card(0), 2000, { ...opts, locked: true })).toBeNull();
    expect(resolveKey("r", card(0), 2000, { ...opts, locked: true })).not.toBeNull();
  });
  it("never fire an already-decided card", () => {
    expect(resolveKey("a", { ...card(0), status: "approved" }, 2000, opts)).toBeNull();
  });
});

describe("voice state", () => {
  it("a new card re-arms: a stray key meant for the old card cannot fire the new one", () => {
    let d = reduce(emptyVoice, { type: "proposal", proposal: proposal({ id: "old" }) }, 0);
    expect(activeCard(d)?.id).toBe("old");
    d = reduce(d, { type: "proposal", proposal: proposal({ id: "new" }) }, 5000);
    const c = activeCard(d);
    expect(c?.id).toBe("new");
    expect(c?.shownAt).toBe(5000);
    expect(resolveKey("a", c, 5200, opts)).toBeNull();
  });

  it("an expired proposal is no longer active", () => {
    let d = reduce(emptyVoice, { type: "proposal", proposal: proposal() }, 0);
    expect(activeCard(d)).not.toBeNull();
    d = reduce(d, { type: "expired", id: "p1" }, 10_100);
    expect(activeCard(d)).toBeNull();
  });

  it("an edit refreshes the card and restarts the arm delay", () => {
    let d = reduce(emptyVoice, { type: "proposal", proposal: proposal() }, 0);
    d = reduce(d, { type: "proposal", proposal: proposal({ created_at_ms: 6000, expires_at_ms: 16_000 }) }, 5000);
    expect(activeCard(d)?.shownAt).toBe(5000);
    expect(activeCard(d)?.expiresAt).toBe(15_000);
  });

  it("a replay seek drops pending cards", () => {
    let d = reduce(emptyVoice, { type: "proposal", proposal: proposal() }, 0);
    d = dropPending(d, 100);
    expect(activeCard(d)).toBeNull();
    expect(d.entries["p1"].p.status).toBe("expired");
  });

  it("tracks the emergency lock", () => {
    expect(reduce(emptyVoice, { type: "lock", locked: true }, 0).locked).toBe(true);
  });
});
