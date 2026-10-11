import type { Alert, ProtectedVolume } from "../engine/types";

const KIND_RANK: Record<ProtectedVolume["kind"], number> = { approach: 0, departure: 1, class_b_floor: 2 };

/** The single alert that gets the prominent card: a "handoff" (the highest severity), then
 * approach over departure over class B floor (same order the engine uses to collapse
 * overlapping volumes, so an aircraft about to cross a runway path outranks traffic that is
 * already inside the Hudson exclusion), then soonest time-to-entry, then highest confidence.
 * Everything else stays in the alert log. Returns null when no handoff is active. */
export function pickProminentAlert(alerts: Alert[], volumes: ProtectedVolume[] = []): Alert | null {
  const kindRank = new Map(volumes.map((v) => [v.id, KIND_RANK[v.kind]]));
  const rank = (a: Alert) => kindRank.get(a.volume_id) ?? KIND_RANK.class_b_floor;
  let best: Alert | null = null;
  for (const a of alerts) {
    if (a.severity !== "handoff") continue;
    if (best === null) {
      best = a;
      continue;
    }
    const byKind = rank(a) - rank(best);
    const byTte = a.time_to_entry_s - best.time_to_entry_s;
    if (byKind < 0 || (byKind === 0 && (byTte < 0 || (byTte === 0 && a.confidence > best.confidence)))) best = a;
  }
  return best;
}
