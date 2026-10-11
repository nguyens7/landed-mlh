import { describe, expect, it } from "vitest";
import {
  applyRateLimits,
  fitVerticalRate,
  VR_DEADBAND_FPM,
  VR_MAX_FPM,
  type AltSample,
} from "./verticalRate";

const series = (f: (t: number) => number, ts: number[]): AltSample[] => ts.map((t) => ({ t, alt_ft: f(t) }));

describe("fitVerticalRate", () => {
  it("recovers an exact linear climb rate and the current altitude", () => {
    // 10 ft/s = 600 fpm
    const s = series((t) => 1000 + 10 * t, [0, 4, 8, 12, 16, 20]);
    const e = fitVerticalRate(s, 20);
    expect(e.reliable).toBe(true);
    expect(e.rate_fpm).toBeCloseTo(600, 3);
    expect(e.alt_ft).toBeCloseTo(1200, 3);
  });

  it("recovers a descent", () => {
    const e = fitVerticalRate(series((t) => 2000 - 8 * t, [0, 3, 6, 9, 12, 15]), 15);
    expect(e.rate_fpm).toBeCloseTo(-480, 3);
  });

  it("ignores samples older than the 25 s window", () => {
    const s = [...series(() => 500, [-100, -60]), ...series((t) => 1000 + 10 * t, [0, 5, 10, 15, 20])];
    const e = fitVerticalRate(s, 20);
    expect(e.n).toBe(5);
    expect(e.rate_fpm).toBeCloseTo(600, 3);
  });

  it("is robust to noise where a two-point difference is not", () => {
    // Level at 600 ft with +/-75 ft jitter: the last-two-point rate is -1,800 fpm.
    const noisy = [600, 675, 540, 660, 560, 675, 600].map((alt_ft, i) => ({ t: i * 4, alt_ft }));
    const twoPoint = ((noisy[6].alt_ft - noisy[5].alt_ft) / 4) * 60;
    expect(Math.abs(twoPoint)).toBeGreaterThan(1000);
    const e = fitVerticalRate(noisy, 24);
    expect(e.rate_fpm).toBe(0);
    expect(Math.abs(e.alt_ft - 600)).toBeLessThan(60);
  });

  it("reports level (0) and unreliable with too few samples or too short a span", () => {
    expect(fitVerticalRate(series((t) => 1000 + 20 * t, [0, 4]), 4)).toMatchObject({ rate_fpm: 0, reliable: false, alt_ft: 1080 });
    expect(fitVerticalRate(series((t) => 1000 + 20 * t, [0, 2, 4]), 4).reliable).toBe(false);
  });

  it("is not dragged over a threshold by a single spiked final sample", () => {
    const e = fitVerticalRate(series((t) => (t === 20 ? 1250 : 1150), [0, 4, 8, 12, 16, 20]), 20);
    expect(e.alt_ft).toBeLessThan(1200);
  });
});

describe("applyRateLimits (clamp and deadband)", () => {
  it("clamps to +/-1,500 fpm", () => {
    expect(applyRateLimits(5000)).toBe(VR_MAX_FPM);
    expect(applyRateLimits(-5000)).toBe(-VR_MAX_FPM);
  });

  it("treats |rate| below the 200 fpm deadband as level", () => {
    expect(applyRateLimits(VR_DEADBAND_FPM - 1)).toBe(0);
    expect(applyRateLimits(-(VR_DEADBAND_FPM - 1))).toBe(0);
    expect(applyRateLimits(VR_DEADBAND_FPM)).toBe(VR_DEADBAND_FPM);
    expect(applyRateLimits(-450)).toBe(-450);
  });

  it("applies the deadband to a fit: a 150 fpm drift reads level", () => {
    const e = fitVerticalRate(series((t) => 1000 + 2.5 * t, [0, 4, 8, 12, 16, 20]), 20);
    expect(e.raw_fpm).toBeCloseTo(150, 3);
    expect(e.rate_fpm).toBe(0);
  });
});
