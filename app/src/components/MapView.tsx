import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// maplibre-gl resolves its worker script from `import.meta.url` inside its own ESM
// bundle, which Vite's dev transform doesn't preserve as an absolute http(s) URL --
// that makes maplibre fall back to an empty worker URL and the map never renders.
// Resolving it ourselves with Vite's `?url` import and setting it explicitly up front
// sidesteps that (works the same in `vite build`, where it resolves to the hashed
// output path).
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useDeskStore } from "../store/useDeskStore";
import { interpolateAircraft } from "../data/interpolate";
import {
  AIRLINER_COLOR,
  HELI_COLORS,
  MEDEVAC_COLOR,
  iconDataUrl,
  iconId,
  iconSvg,
  type IconShape,
} from "./mapIcons";

maplibregl.setWorkerUrl(maplibreWorkerUrl as string);

const BASEMAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const CENTER: [number, number] = [-73.92, 40.76];

const SEVERITY_COLOR: Record<string, string> = {
  advisory: "#39c0ff",
  caution: "#ffb020",
  handoff: "#ff3b3b",
};

/** Small ring buffer of recent positions per aircraft, for the trail layer. Kept outside
 * React state (it's a rendering concern, not app state) and cleared on seek-backwards. */
const trails = new Map<string, [number, number][]>();
let lastT = 0;
let lastEpoch = 0;

export function MapView() {
  const mapDivRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  const corridors = useDeskStore((s) => s.corridors);
  const protectedVolumesGeo = useDeskStore((s) => s.protectedVolumesGeo);
  const approachPaths = useDeskStore((s) => s.approachPaths);
  const referencePoints = useDeskStore((s) => s.referencePoints);
  const snapshots = useDeskStore((s) => s.snapshots);
  const alerts = useDeskStore((s) => s.alerts);
  const currentT = useDeskStore((s) => s.currentT);
  const loaded = useDeskStore((s) => s.loaded);
  const seekEpoch = useDeskStore((s) => s.seekEpoch);
  const aircraftByHex = useDeskStore((s) => s.aircraftByHex);
  const fixedWingByHex = useDeskStore((s) => s.fixedWingByHex);

  // one-time map + static layer setup
  useEffect(() => {
    if (!mapDivRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapDivRef.current,
      style: BASEMAP_STYLE,
      center: CENTER,
      zoom: 10.6,
      attributionControl: false,
    });
    mapRef.current = map;

    map.on("load", () => {
      map.addSource("corridors", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "corridors-line",
        type: "line",
        source: "corridors",
        paint: { "line-color": "#39c0ff", "line-width": 10, "line-opacity": 0.12 },
      });

      map.addSource("approach-paths", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "approach-paths-line",
        type: "line",
        source: "approach-paths",
        paint: { "line-color": "#ff8a3d", "line-width": 2, "line-dasharray": [2, 2] },
      });

      map.addSource("protected-volumes", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "protected-volumes-fill",
        type: "fill",
        source: "protected-volumes",
        paint: { "fill-color": "#ff3b3b", "fill-opacity": 0.08 },
      });
      map.addLayer({
        id: "protected-volumes-outline",
        type: "line",
        source: "protected-volumes",
        paint: { "line-color": "#ff3b3b", "line-width": 1.5, "line-opacity": 0.5 },
      });

      map.addSource("reference-points", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "reference-points-circle",
        type: "circle",
        source: "reference-points",
        paint: { "circle-color": "#8b9bab", "circle-radius": 4 },
      });
      map.addLayer({
        id: "reference-points-label",
        type: "symbol",
        source: "reference-points",
        layout: {
          "text-field": ["get", "name"],
          "text-size": 11,
          "text-offset": [0, 1.1],
          "text-anchor": "top",
        },
        paint: { "text-color": "#8b9bab", "text-halo-color": "#0a0e14", "text-halo-width": 1 },
      });

      map.addSource("trails", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "trails-line",
        type: "line",
        source: "trails",
        paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.6 },
      });

      map.addSource("cones", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "cones-line",
        type: "line",
        source: "cones",
        paint: { "line-color": "#ff3b3b", "line-width": 2, "line-dasharray": [1, 1] },
      });
      map.addLayer({
        id: "cones-point",
        type: "circle",
        source: "cones",
        filter: ["==", ["get", "kind"], "entry"],
        paint: { "circle-color": "#ff3b3b", "circle-radius": 6, "circle-opacity": 0.7 },
      });

      // Display-only airliners: drawn under the helicopters, never evaluated by the engine.
      map.addSource("fixedwing", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "fixedwing-icon",
        type: "symbol",
        source: "fixedwing",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-size": 0.7,
          "icon-rotate": ["get", "track_deg"],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
        paint: { "icon-opacity": 0.8 },
      });
      map.addLayer({
        id: "fixedwing-label",
        type: "symbol",
        source: "fixedwing",
        layout: {
          "text-field": ["get", "label"],
          "text-size": 11,
          "text-variable-anchor": ["top", "bottom", "left", "right"],
          "text-radial-offset": 1.1,
          "text-justify": "auto",
          "text-allow-overlap": false,
        },
        paint: { "text-color": AIRLINER_COLOR, "text-halo-color": "#0a0e14", "text-halo-width": 1.2 },
      });

      map.addSource("aircraft", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "aircraft-icon",
        type: "symbol",
        source: "aircraft",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-size": ["case", ["get", "simulated"], 0.95, 0.8],
          "icon-rotate": ["get", "track_deg"],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "symbol-sort-key": ["get", "z"],
        },
      });
      // Labels declutter: colliding labels are hidden (alerted aircraft are placed first via
      // the sort key) and the rest try other anchors before giving up. The medevac label is
      // its own layer that always shows.
      const labelPaint = { "text-color": "#e6edf3", "text-halo-color": "#0a0e14", "text-halo-width": 1.2 };
      map.addLayer({
        id: "aircraft-label",
        type: "symbol",
        source: "aircraft",
        filter: ["!", ["get", "simulated"]],
        layout: {
          "text-field": ["get", "label"],
          "text-size": 11,
          "text-variable-anchor": ["top", "bottom", "left", "right"],
          "text-radial-offset": 1.0,
          "text-justify": "auto",
          "text-allow-overlap": false,
          "symbol-sort-key": ["get", "prio"],
        },
        paint: labelPaint,
      });
      map.addLayer({
        id: "aircraft-label-sim",
        type: "symbol",
        source: "aircraft",
        filter: ["get", "simulated"],
        layout: {
          "text-field": ["get", "label"],
          "text-size": 12,
          "text-offset": [0, 1.3],
          "text-anchor": "top",
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: labelPaint,
      });

      registerIcons(map);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // static geometry, once loaded
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (corridors) (map.getSource("corridors") as maplibregl.GeoJSONSource)?.setData(corridors as GeoJSON.FeatureCollection);
      if (protectedVolumesGeo)
        (map.getSource("protected-volumes") as maplibregl.GeoJSONSource)?.setData(protectedVolumesGeo as GeoJSON.FeatureCollection);
      if (approachPaths)
        (map.getSource("approach-paths") as maplibregl.GeoJSONSource)?.setData(approachPaths as GeoJSON.FeatureCollection);
      if (referencePoints)
        (map.getSource("reference-points") as maplibregl.GeoJSONSource)?.setData(referencePoints as GeoJSON.FeatureCollection);
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [corridors, protectedVolumesGeo, approachPaths, referencePoints, loaded]);

  // live aircraft + trails + alert cones, every tick
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    // any seek (scrubber, jump to conflict) or backwards time drops the stale trails
    if (currentT < lastT || seekEpoch !== lastEpoch) trails.clear();
    lastT = currentT;
    lastEpoch = seekEpoch;

    const severityByHex = new Map<string, string>();
    for (const a of alerts) {
      const prev = severityByHex.get(a.aircraft.hex);
      if (!prev || rank(a.severity) > rank(prev)) severityByHex.set(a.aircraft.hex, a.severity);
    }

    const features: GeoJSON.Feature[] = [];
    const trailFeatures: GeoJSON.Feature[] = [];
    for (const s of snapshots) {
      const sev = severityByHex.get(s.hex);
      const color = s.simulated ? "#ff5fe0" : sev ? SEVERITY_COLOR[sev] : "#39c0ff";

      const trail = trails.get(s.hex) ?? [];
      trail.push([s.lon, s.lat]);
      if (trail.length > 40) trail.shift();
      trails.set(s.hex, trail);
      if (trail.length > 1) {
        trailFeatures.push({
          type: "Feature",
          properties: { color },
          geometry: { type: "LineString", coordinates: trail },
        });
      }

      const isMedevac = s.simulated || aircraftByHex[s.hex]?.role_guess === "medevac";
      features.push({
        type: "Feature",
        properties: {
          hex: s.hex,
          reg: s.reg,
          track_deg: s.track_deg,
          simulated: s.simulated,
          icon: iconId(isMedevac ? "medevac" : "heli", color),
          z: isMedevac ? 5 : sev ? rank(sev) : 0, // higher draws on top
          color,
          label: `${s.reg}\n${Math.round(s.alt_ft)} ft`,
          prio: s.simulated ? 0 : sev ? 3 - rank(sev) : 4, // lower = labelled first

        },
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      });
    }
    (map.getSource("aircraft") as maplibregl.GeoJSONSource)?.setData({ type: "FeatureCollection", features });

    // airliners: interpolate for display only (the engine never sees these)
    const fwFeatures: GeoJSON.Feature[] = [];
    for (const ac of Object.values(fixedWingByHex)) {
      const f = interpolateAircraft(ac, currentT);
      if (!f) continue;
      fwFeatures.push({
        type: "Feature",
        properties: {
          track_deg: f.track_deg,
          icon: iconId("plane", AIRLINER_COLOR),
          label: `${f.reg}\n${Math.round(f.alt_ft)} ft`,
        },
        geometry: { type: "Point", coordinates: [f.lon, f.lat] },
      });
    }
    (map.getSource("fixedwing") as maplibregl.GeoJSONSource)?.setData({
      type: "FeatureCollection",
      features: fwFeatures,
    });
    (map.getSource("trails") as maplibregl.GeoJSONSource)?.setData({
      type: "FeatureCollection",
      features: trailFeatures,
    });

    const coneFeatures: GeoJSON.Feature[] = [];
    for (const a of alerts) {
      if (a.severity !== "handoff") continue;
      const ac = snapshots.find((s) => s.hex === a.aircraft.hex);
      if (!ac) continue;
      coneFeatures.push({
        type: "Feature",
        properties: { kind: "line" },
        geometry: {
          type: "LineString",
          coordinates: [
            [ac.lon, ac.lat],
            [a.entry_point.lon, a.entry_point.lat],
          ],
        },
      });
      coneFeatures.push({
        type: "Feature",
        properties: { kind: "entry" },
        geometry: { type: "Point", coordinates: [a.entry_point.lon, a.entry_point.lat] },
      });
    }
    (map.getSource("cones") as maplibregl.GeoJSONSource)?.setData({
      type: "FeatureCollection",
      features: coneFeatures,
    });
  }, [snapshots, alerts, currentT, seekEpoch, aircraftByHex, fixedWingByHex]);

  return (
    <>
      <div ref={mapDivRef} className="map-view" />
      <MapLegend />
    </>
  );
}

function rank(sev: string): number {
  return sev === "handoff" ? 3 : sev === "caution" ? 2 : sev === "advisory" ? 1 : 0;
}

function emptyFC(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

/** Rasterize each shape x color to a map image (sync-free: images load async, the layer
 * simply renders each icon once its image lands). */
function registerIcons(map: maplibregl.Map): void {
  const combos: [IconShape, string][] = [
    ...HELI_COLORS.map((c) => ["heli", c] as [IconShape, string]),
    ...[MEDEVAC_COLOR, ...HELI_COLORS].map((c) => ["medevac", c] as [IconShape, string]),
    ["plane", AIRLINER_COLOR],
  ];
  for (const [shape, color] of combos) {
    const id = iconId(shape, color);
    const img = new Image();
    img.onload = () => {
      if (map.hasImage(id)) return;
      const bmp = document.createElement("canvas");
      bmp.width = img.width;
      bmp.height = img.height;
      const ctx = bmp.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(img, 0, 0);
      map.addImage(id, ctx.getImageData(0, 0, bmp.width, bmp.height));
    };
    img.src = iconDataUrl(shape, color);
  }
}

const LEGEND_ITEMS: { shape: IconShape; color: string; text: string }[] = [
  { shape: "heli", color: HELI_COLORS[0], text: "Helicopter" },
  { shape: "medevac", color: MEDEVAC_COLOR, text: "Medevac (SIM)" },
  { shape: "plane", color: AIRLINER_COLOR, text: "Airliner" },
];

function MapLegend() {
  return (
    <div
      aria-label="Map legend"
      style={{
        position: "absolute",
        left: 12,
        bottom: 40,
        display: "flex",
        gap: 16,
        alignItems: "center",
        padding: "6px 12px",
        background: "rgba(10,14,20,0.82)",
        border: "1px solid #2a3441",
        borderRadius: 6,
        color: "#e6edf3",
        fontSize: 13,
        zIndex: 2,
        pointerEvents: "none",
      }}
    >
      {LEGEND_ITEMS.map((it) => (
        <span key={it.text} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span
            style={{ width: 22, height: 22, display: "inline-block" }}
            dangerouslySetInnerHTML={{ __html: iconSvg(it.shape, it.color).replace(/width="64" height="64"/, 'width="22" height="22"') }}
          />
          {it.text}
        </span>
      ))}
    </div>
  );
}
