// Pure builders for the focused-aircraft highlight (no maplibre import, so they unit test in node).

import type { Alert } from "../engine/types";

/** Opacity of every non-focused aircraft icon and label while a focus exists. */
export const DIM_OPACITY = 0.45;

/** The hex to highlight: an explicit focus if set, else the aircraft of the prominent (AlertCard) alert. */
export function effectiveFocusHex(focusedHex: string | null, prominent: Alert | null): string | null {
  return focusedHex ?? prominent?.aircraft.hex ?? null;
}

/** Opacity expression for aircraft icons or labels: full for the focused hex, dimmed for others.
 * With no focus the base opacity is returned unchanged. */
export function focusOpacity(focusHex: string | null, base = 1): number | unknown[] {
  if (!focusHex) return base;
  return ["case", ["==", ["get", "hex"], focusHex], 1, base * DIM_OPACITY];
}

/** Sort key so the focused aircraft draws on top (higher = on top). */
export function focusSortKey(focusHex: string | null): unknown[] {
  if (!focusHex) return ["get", "z"];
  return ["case", ["==", ["get", "hex"], focusHex], 100, ["get", "z"]];
}

/** Ring colour: red for handoff, amber for anything else (caution). */
export function focusRingColor(severity: string | undefined): string {
  return severity === "handoff" ? "#ff3b3b" : "#ffb020";
}

/** Pulse state at time `ms`: radius in px (cycles 16 to 44 every 1.4 s) and opacity (fades as it grows). */
export function pulseAt(ms: number): { radius: number; opacity: number } {
  const phase = (ms % 1400) / 1400;
  return { radius: 16 + 28 * phase, opacity: 0.85 * (1 - phase) + 0.1 };
}

/** Callout text, e.g. "N312LM, 600 ft". */
export function calloutText(reg: string, altFt: number): string {
  return `${reg}, ${Math.round(altFt)} ft`;
}
