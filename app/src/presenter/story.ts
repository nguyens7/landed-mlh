// Plain-English wording for the presenter hero card. Words only: every number shown comes
// straight from the engine alert.
import type { Alert, ProtectedVolume, Severity } from "../engine/types";
import type { ReplayAircraft } from "../data/types";

export type StoryTone = "normal" | "caution" | "handoff";

/** The status word on the hero card, matching the map colors (blue, amber, red). */
export function statusWord(severity: Severity | null): string {
  if (severity === "handoff") return "Handed to controller";
  if (severity === "caution") return "Caution";
  return "Normal";
}

export function toneOf(severity: Severity | null): StoryTone {
  if (severity === "handoff") return "handoff";
  if (severity === "caution") return "caution";
  return "normal";
}

/** "Medevac" for the simulated medevac, else "Helicopter N123AB". */
export function whoLabel(reg: string, ac: ReplayAircraft | undefined): string {
  if (ac?.simulated || ac?.role_guess === "medevac") return "Medevac";
  return `Helicopter ${reg}`;
}

/** Where the aircraft is heading, in words a judge knows. */
export function placeLabel(volume: ProtectedVolume | undefined): string {
  if (!volume) return "protected airspace";
  if (volume.kind === "approach") return "LaGuardia arrivals";
  if (volume.kind === "departure") return "LaGuardia departures";
  return "the Class B floor over the Hudson";
}

/** One short line: "Medevac heading into LaGuardia arrivals". */
export function headline(alert: Alert, ac: ReplayAircraft | undefined, volume: ProtectedVolume | undefined): string {
  return `${whoLabel(alert.aircraft.reg, ac)} heading into ${placeLabel(volume)}`;
}

/** The engine reason without its leading "REG: " (the card already names the aircraft). */
export function detail(alert: Alert): string {
  const prefix = `${alert.aircraft.reg}: `;
  return alert.reason.startsWith(prefix) ? alert.reason.slice(prefix.length) : alert.reason;
}

/** The single alert the hero card shows: the given handoff, else the soonest caution. */
export function pickHeroAlert(handoff: Alert | null, alerts: Alert[]): Alert | null {
  if (handoff) return handoff;
  let best: Alert | null = null;
  for (const a of alerts) {
    if (a.severity !== "caution") continue;
    if (!best || a.time_to_entry_s < best.time_to_entry_s) best = a;
  }
  return best;
}
