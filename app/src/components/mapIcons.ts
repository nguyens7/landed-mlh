// Inline SVG silhouettes for the map, all drawn pointing north (up) so MapLibre's
// `icon-rotate` = track_deg turns them to the direction of travel.

export type IconShape = "heli" | "medevac" | "plane";

export const ICON_SIZE_PX = 64;

const OUTLINE = "#0a0e14";

export function iconSvg(shape: IconShape, color: string): string {
  const stroke = `stroke="${OUTLINE}" stroke-width="2.5" stroke-linejoin="round"`;
  let body: string;
  if (shape === "plane") {
    body = `<path ${stroke} fill="${color}" d="M32 4 C35 4 36.5 9 36.5 16 L36.5 25 L60 39 L60 45 L36.5 38 L36.5 50 L46 56 L46 61 L32 57.5 L18 61 L18 56 L27.5 50 L27.5 38 L4 45 L4 39 L27.5 25 L27.5 16 C27.5 9 29 4 32 4 Z"/>`;
  } else {
    // rotor disk + fuselage + tail boom + tail rotor
    body =
      `<circle cx="32" cy="27" r="23" fill="${color}" fill-opacity="0.18" stroke="${color}" stroke-width="2.5"/>` +
      `<path ${stroke} fill="${color}" d="M30.2 36 L33.8 36 L33.8 56 L38 56 L38 59 L26 59 L26 56 L30.2 56 Z"/>` +
      `<ellipse ${stroke} cx="32" cy="26" rx="8" ry="12" fill="${color}"/>` +
      `<path d="M27 14 Q32 10 37 14" fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="2.5" stroke-linecap="round"/>`;
    if (shape === "medevac") {
      body +=
        `<circle cx="50" cy="50" r="12" fill="#ffffff" stroke="${OUTLINE}" stroke-width="2"/>` +
        `<path d="M47 41.5 H53 V47 H58.5 V53 H53 V58.5 H47 V53 H41.5 V47 H47 Z" fill="#e5231b"/>`;
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${ICON_SIZE_PX}" height="${ICON_SIZE_PX}" viewBox="0 0 64 64">${body}</svg>`;
}

export function iconDataUrl(shape: IconShape, color: string): string {
  return "data:image/svg+xml;base64," + btoa(iconSvg(shape, color));
}

/** Image id used with `map.addImage`; the aircraft layer picks it via a data-driven property. */
export function iconId(shape: IconShape, color: string): string {
  return `${shape}-${color.replace("#", "")}`;
}

export const AIRLINER_COLOR = "#aab6c4";
export const MEDEVAC_COLOR = "#ff5fe0";
export const HELI_COLORS = ["#39c0ff", "#ffb020", "#ff3b3b"];
