import { describe, expect, it } from "vitest";
import type { Alert } from "../engine/types";
import { calloutText, effectiveFocusHex, focusOpacity, focusRingColor, focusSortKey, pulseAt } from "./focusStyle";

describe("focus expressions", () => {
  it("returns the base opacity when nothing is focused", () => {
    expect(focusOpacity(null)).toBe(1);
    expect(focusOpacity(null, 0.8)).toBe(0.8);
  });
  it("keys opacity and sort order on the focused hex", () => {
    expect(focusOpacity("abc123", 0.8)).toEqual(["case", ["==", ["get", "hex"], "abc123"], 1, 0.8 * 0.45]);
    expect(focusSortKey("abc123")).toEqual(["case", ["==", ["get", "hex"], "abc123"], 100, ["get", "z"]]);
    expect(focusSortKey(null)).toEqual(["get", "z"]);
  });
  it("prefers an explicit focus, else the prominent alert's aircraft", () => {
    const alert = { aircraft: { hex: "h1", reg: "N1" } } as Alert;
    expect(effectiveFocusHex("h2", alert)).toBe("h2");
    expect(effectiveFocusHex(null, alert)).toBe("h1");
    expect(effectiveFocusHex(null, null)).toBeNull();
  });
  it("colours the ring by severity and pulses within bounds", () => {
    expect(focusRingColor("handoff")).toBe("#ff3b3b");
    expect(focusRingColor("caution")).toBe("#ffb020");
    for (const ms of [0, 300, 700, 1399]) {
      const p = pulseAt(ms);
      expect(p.radius).toBeGreaterThanOrEqual(16);
      expect(p.radius).toBeLessThanOrEqual(44);
      expect(p.opacity).toBeGreaterThan(0);
      expect(p.opacity).toBeLessThanOrEqual(1);
    }
  });
  it("formats the callout", () => {
    expect(calloutText("N312LM", 600.4)).toBe("N312LM, 600 ft");
  });
});
