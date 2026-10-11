import { describe, expect, it } from "vitest";
import {
  destPoint,
  distanceNm,
  distanceToPolygonNm,
  headingStdDev,
  pointInPolygon,
} from "./geometry";

describe("destPoint / distanceNm", () => {
  it("round-trips: distance to a destination point matches the requested distance", () => {
    const start = { lat: 40.75, lon: -73.95 };
    const d = destPoint(start.lat, start.lon, 90, 5);
    expect(distanceNm(start.lat, start.lon, d.lat, d.lon)).toBeCloseTo(5, 1);
  });

  it("heading 90 (due east) increases longitude, not latitude", () => {
    const start = { lat: 40.75, lon: -73.95 };
    const d = destPoint(start.lat, start.lon, 90, 2);
    expect(d.lon).toBeGreaterThan(start.lon);
    expect(d.lat).toBeCloseTo(start.lat, 2);
  });
});

describe("pointInPolygon", () => {
  const square: [number, number][] = [
    [-74.0, 40.7],
    [-74.0, 40.8],
    [-73.9, 40.8],
    [-73.9, 40.7],
    [-74.0, 40.7],
  ];

  it("detects a point inside the ring", () => {
    expect(pointInPolygon(40.75, -73.95, square)).toBe(true);
  });

  it("detects a point outside the ring", () => {
    expect(pointInPolygon(40.75, -73.5, square)).toBe(false);
  });
});

describe("distanceToPolygonNm", () => {
  const square: [number, number][] = [
    [-74.0, 40.7],
    [-74.0, 40.8],
    [-73.9, 40.8],
    [-73.9, 40.7],
    [-74.0, 40.7],
  ];

  it("is 0 for a point inside", () => {
    expect(distanceToPolygonNm(40.75, -73.95, square)).toBe(0);
  });

  it("is positive and roughly correct for a point outside", () => {
    const d = distanceToPolygonNm(40.75, -73.8, square);
    expect(d).toBeGreaterThan(0);
    // roughly 0.1 deg lon ~ 4.5 nm at this latitude
    expect(d).toBeGreaterThan(3);
    expect(d).toBeLessThan(6);
  });
});

describe("headingStdDev", () => {
  it("is 0 for a perfectly steady heading", () => {
    expect(headingStdDev([90, 90, 90, 90])).toBeCloseTo(0, 5);
  });

  it("is small across the 0/360 wraparound, not huge", () => {
    const wrapped = headingStdDev([358, 2, 359, 1]);
    const unwrapped = headingStdDev([10, 12, 9, 11]);
    expect(wrapped).toBeLessThan(15);
    expect(wrapped).toBeCloseTo(unwrapped, 0);
  });

  it("is large for a wildly varying heading", () => {
    expect(headingStdDev([0, 90, 180, 270])).toBeGreaterThan(60);
  });
});
