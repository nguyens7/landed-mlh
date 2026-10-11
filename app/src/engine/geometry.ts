// Geodesy + polygon helpers used by the conflict engine. Pure functions, no I/O.

const EARTH_R_NM = 3440.065;

export function toRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

export function toDeg(rad: number): number {
  return (rad * 180) / Math.PI;
}

/** Destination point given a start (lat, lon), a true bearing (deg), and a great-circle
 * distance in nautical miles. */
export function destPoint(
  lat: number,
  lon: number,
  bearingTrue: number,
  distNm: number,
): { lat: number; lon: number } {
  const lat1 = toRad(lat);
  const lon1 = toRad(lon);
  const brg = toRad(bearingTrue);
  const dR = distNm / EARTH_R_NM;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(dR) + Math.cos(lat1) * Math.sin(dR) * Math.cos(brg),
  );
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(brg) * Math.sin(dR) * Math.cos(lat1),
      Math.cos(dR) - Math.sin(lat1) * Math.sin(lat2),
    );
  return { lat: toDeg(lat2), lon: toDeg(lon2) };
}

/** Haversine distance in nautical miles. */
export function distanceNm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const phi1 = toRad(lat1);
  const phi2 = toRad(lat2);
  const dPhi = phi2 - phi1;
  const dLambda = toRad(lon2 - lon1);
  const a =
    Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
  return 2 * EARTH_R_NM * Math.asin(Math.sqrt(a));
}

/** Ray-casting point-in-polygon test. `ring` is [lon, lat] pairs, first === last (GeoJSON
 * winding). Good enough at NYC's latitude/scale; we don't need geodesic exactness here. */
export function pointInPolygon(lat: number, lon: number, ring: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersects =
      yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

/** Shortest distance (nm) from a point to a polygon's boundary (0 if inside). Used for
 * "near miss" caution-tier scoring when a path doesn't actually enter the volume. */
export function distanceToPolygonNm(
  lat: number,
  lon: number,
  ring: [number, number][],
): number {
  if (pointInPolygon(lat, lon, ring)) return 0;
  let min = Infinity;
  for (let i = 0; i < ring.length - 1; i++) {
    const [lon1, lat1] = ring[i];
    const [lon2, lat2] = ring[i + 1];
    min = Math.min(min, distanceToSegmentNm(lat, lon, lat1, lon1, lat2, lon2));
  }
  return min;
}

function distanceToSegmentNm(
  lat: number,
  lon: number,
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  // local equirectangular projection (nm), fine at this scale/latitude
  const lat0 = 40.75;
  const k = Math.cos(toRad(lat0)) * 60;
  const toXY = (la: number, lo: number) => [(lo + 73.95) * k, (la - lat0) * 60];
  const [px, py] = toXY(lat, lon);
  const [ax, ay] = toXY(lat1, lon1);
  const [bx, by] = toXY(lat2, lon2);
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}

export const MAX_HEADING_STDDEV_DEG = 180;

/** Circular standard deviation of a list of track headings (deg), accounting for wraparound
 * at 360. Returns degrees; 0 = perfectly steady heading. */
export function headingStdDev(headings: number[]): number {
  // Zero or one heading is no evidence of a steady track: report the maximum spread so the
  // stability score is low rather than perfect.
  if (headings.length < 2) return MAX_HEADING_STDDEV_DEG;
  const sins = headings.map((h) => Math.sin(toRad(h)));
  const coss = headings.map((h) => Math.cos(toRad(h)));
  const meanSin = sins.reduce((a, b) => a + b, 0) / sins.length;
  const meanCos = coss.reduce((a, b) => a + b, 0) / coss.length;
  const r = Math.hypot(meanSin, meanCos);
  // circular variance -> approximate angular std dev in degrees
  const variance = Math.max(0, 1 - r);
  return toDeg(Math.sqrt(variance * 2));
}
