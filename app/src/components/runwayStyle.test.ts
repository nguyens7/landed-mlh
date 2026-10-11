import { describe, expect, it } from "vitest";
import { runwayStrips, volumeState } from "./runwayStyle";

const props = [
  { id: "a22_0", kind: "approach", runway: "22" },
  { id: "a22_1", kind: "approach", runway: "22" },
  { id: "a31_0", kind: "approach", runway: "31" },
  { id: "d4", kind: "departure", runway: "4" },
  { id: "d13", kind: "departure", runway: "13" },
  { id: "cb", kind: "class_b_floor", runway: null },
];

describe("volumeState", () => {
  const none = new Set<string>();
  it("styles by runway configuration when nothing alerts", () => {
    expect(props.map((p) => volumeState(p, none, props))).toEqual([
      "active-arrival",
      "active-arrival",
      "inactive",
      "inactive",
      "active-departure",
      "inactive",
    ]);
  });
  it("turns the whole alerted logical volume red, and only it", () => {
    const alerted = new Set(["a22_1"]);
    expect(props.map((p) => volumeState(p, alerted, props))).toEqual([
      "alert",
      "alert",
      "inactive",
      "inactive",
      "active-departure",
      "inactive",
    ]);
  });
});

describe("runwayStrips", () => {
  it("runs each threshold about 7,000 ft along the landing heading and labels it", () => {
    const { lines, labels } = runwayStrips([
      { runway: "22", threshold_lat: 40.785437, threshold_lon: -73.870673, bearing_true: 212 },
    ]);
    expect(labels).toEqual([{ name: "Runway 22", lon: -73.870673, lat: 40.785437 }]);
    const far = lines[0][1];
    expect(far[1]).toBeLessThan(40.785437);
    expect(far[0]).toBeLessThan(-73.870673);
    expect(Math.abs(far[1] - 40.7692)).toBeLessThan(0.002);
  });
});
