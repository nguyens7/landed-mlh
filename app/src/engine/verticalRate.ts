// Vertical-rate estimation for the conflict engine. Pure functions, no I/O.
//
// Why not a two-point difference: ADS-B barometric altitude is quantized (25 ft) and
// jittery at ~3-5 s update spacing, so (alt2 - alt1) / dt routinely reads +/-1,000 fpm
// for a level aircraft. Extrapolating that over a 90 s horizon fabricated ~1,500 ft of
// phantom climb and produced false Class B handoffs (N84BL never exceeded 640 ft).
//
// Estimator, in order:
//   1. Least-squares line alt = a + b*t through every sample in the last
//      VR_WINDOW_S seconds (default 25 s, ~6 points at the replay's 4 s spacing).
//      The slope b is the raw rate; the line evaluated at "now" is the smoothed altitude.
//      Fewer than VR_MIN_SAMPLES samples, or a time span under VR_MIN_SPAN_S, is too
//      little data for a slope to mean anything: the rate is reported as 0 (level) and
//      `reliable` is false.
//   2. Clamp to +/-VR_MAX_FPM (1,500 fpm). Helicopters in this airspace do not sustain
//      more; larger values are noise or altitude-source discontinuities.
//   3. Deadband: |rate| < VR_DEADBAND_FPM (200 fpm) is treated as level (0). Below that
//      the slope is indistinguishable from altimetry noise over a 25 s window.

export const VR_WINDOW_S = 25;
export const VR_MIN_SAMPLES = 3;
export const VR_MIN_SPAN_S = 8;
export const VR_MAX_FPM = 1500;
export const VR_DEADBAND_FPM = 200;

export interface AltSample {
  t: number;
  alt_ft: number;
}

export interface VerticalEstimate {
  /** Clamped, deadbanded rate in ft/min. 0 means level (or too little data). */
  rate_fpm: number;
  /** Unclamped, un-deadbanded least-squares slope in ft/min (diagnostics). */
  raw_fpm: number;
  /** Smoothed altitude at `now`: the fitted line evaluated at now (latest raw altitude if unreliable). */
  alt_ft: number;
  /** Number of samples used in the fit. */
  n: number;
  /** True when the fit had enough samples and time span to be trusted. */
  reliable: boolean;
}

export function applyRateLimits(rawFpm: number): number {
  const clamped = Math.max(-VR_MAX_FPM, Math.min(VR_MAX_FPM, rawFpm));
  return Math.abs(clamped) < VR_DEADBAND_FPM ? 0 : clamped;
}

/** Least-squares fit of altitude vs time over the last `windowS` seconds before `now`.
 * `samples` need not be sorted. Samples after `now` are ignored. Returns alt_ft NaN only
 * when there are no samples at all in the window. */
export function fitVerticalRate(
  samples: AltSample[],
  now: number,
  windowS = VR_WINDOW_S,
): VerticalEstimate {
  const pts = samples.filter((s) => s.t <= now && s.t >= now - windowS);
  if (pts.length === 0) return { rate_fpm: 0, raw_fpm: 0, alt_ft: Number.NaN, n: 0, reliable: false };
  const latest = pts.reduce((a, b) => (b.t >= a.t ? b : a));

  const tMin = Math.min(...pts.map((p) => p.t));
  const tMax = Math.max(...pts.map((p) => p.t));
  if (pts.length < VR_MIN_SAMPLES || tMax - tMin < VR_MIN_SPAN_S) {
    return { rate_fpm: 0, raw_fpm: 0, alt_ft: latest.alt_ft, n: pts.length, reliable: false };
  }

  // Center on the mean time for numerical conditioning; the slope is unaffected.
  const n = pts.length;
  const meanT = pts.reduce((s, p) => s + p.t, 0) / n;
  const meanA = pts.reduce((s, p) => s + p.alt_ft, 0) / n;
  // Anchor point (medianT, median): for linear data the median altitude occurs at the median
  // time, so the anchor lies on the LS line.
  const med = (xs: number[]) => {
    const s = [...xs].sort((a, b) => a - b);
    return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
  };
  const median = med(pts.map((p) => p.alt_ft));
  const medianT = med(pts.map((p) => p.t));
  let sxx = 0;
  let sxy = 0;
  for (const p of pts) {
    sxx += (p.t - meanT) ** 2;
    sxy += (p.t - meanT) * (p.alt_ft - meanA);
  }
  const slopeFtPerS = sxx > 0 ? sxy / sxx : 0;
  const raw_fpm = slopeFtPerS * 60;
  return {
    rate_fpm: applyRateLimits(raw_fpm),
    raw_fpm,
    // Smoothed altitude: the LS slope anchored at the window's *median* altitude rather than
    // its mean, so a single spiked sample cannot drag the current altitude over a threshold.
    // For a clean linear climb median == mean and this is the plain LS fit.
    alt_ft: median + slopeFtPerS * (now - medianT),
    n,
    reliable: true,
  };
}
