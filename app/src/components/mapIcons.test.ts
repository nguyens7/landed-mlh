import { describe, expect, it } from "vitest";
import { AIRLINER_COLOR, HELI_COLORS, ICON_COMBOS, MEDEVAC_COLOR, iconId } from "./mapIcons";

describe("registered aircraft icon images", () => {
  const ids = new Set(ICON_COMBOS.map(([s, c]) => iconId(s, c)));
  it("covers every helicopter status color, the medevac and the airliner", () => {
    for (const c of HELI_COLORS) expect(ids.has(iconId("heli", c))).toBe(true);
    expect(ids.has(iconId("medevac", MEDEVAC_COLOR))).toBe(true);
    expect(ids.has(iconId("plane", AIRLINER_COLOR))).toBe(true);
  });
});
