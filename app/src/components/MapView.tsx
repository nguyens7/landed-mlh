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
  ICON_COMBOS,
  MEDEVAC_COLOR,
  iconDataUrl,
  iconId,
  iconSvg,
  type IconShape,
} from "./mapIcons";

import { DEFAULT_RUNWAY_CONFIG } from "../engine/runwayConfig";
import { destPoint } from "../engine/geometry";
import { runwayStrips, volumeState } from "./runwayStyle";
import { pickProminentAlert } from "../store/prominentAlert";
import {
  DIM_OPACITY,
  calloutText,
  effectiveFocusHex,
  focusOpacity,
  focusRingColor,
  focusSortKey,
  pulseAt,
} from "./focusStyle";

const AMBER = "#F29E4C";
const RUNWAY_GRAY = "#C9CED6";
const MUTED_GRAY = "#8b9bab";

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

  const volumes = useDeskStore((s) => s.volumes);
  const storeFocusHex = useDeskStore((s) => s.focusedHex);
  // default focus: the aircraft the AlertCard is about
  const focusHex = effectiveFocusHex(storeFocusHex, pickProminentAlert(alerts, volumes));
  // Stable key so the static-geometry effect reruns only when the alerted volumes change, not every
  // tick (re-setting the volumes source each tick keeps isStyleLoaded() false and starves the aircraft
  // effect). With a focused aircraft, only its volume turns red, so other alerts don't compete.
  const alertVolumeKey = [
    ...new Set((focusHex ? alerts.filter((a) => a.aircraft.hex === focusHex) : alerts).map((a) => a.volume_id)),
  ]
    .sort()
    .join("|");
  const snapshotsRef = useRef(snapshots);
  snapshotsRef.current = snapshots;

  // dim everyone else, raise the focused aircraft
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer("aircraft-icon")) return;
      map.setPaintProperty("aircraft-icon", "icon-opacity", focusOpacity(focusHex) as never);
      map.setLayoutProperty("aircraft-icon", "symbol-sort-key", focusSortKey(focusHex) as never);
      map.setPaintProperty("aircraft-label", "text-opacity", focusOpacity(focusHex) as never);
      map.setPaintProperty("aircraft-label-sim", "text-opacity", focusOpacity(focusHex) as never);
      // airliners have no hex: dim them as a group
      map.setPaintProperty("fixedwing-icon", "icon-opacity", focusHex ? 0.8 * DIM_OPACITY : 0.8);
      map.setPaintProperty("fixedwing-label", "text-opacity", focusHex ? DIM_OPACITY : 1);
      // the callout replaces the focused aircraft's own label
      const notFocused: unknown[] = focusHex ? ["!=", ["get", "hex"], focusHex] : ["literal", true];
      map.setFilter("aircraft-label", ["all", ["!", ["get", "simulated"]], notFocused] as never);
      map.setFilter("aircraft-label-sim", ["all", ["get", "simulated"], notFocused] as never);
    };
    if (map.getLayer("aircraft-icon")) apply();
    else map.once("load", apply);
  }, [focusHex, loaded]);

  // ease the camera only when the focus changes, and only if the aircraft is off-screen or under a card
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focusHex) return;
    const s = snapshotsRef.current.find((x) => x.hex === focusHex);
    if (!s) return;
    const { x, y } = map.project([s.lon, s.lat]);
    const { clientWidth: w, clientHeight: h } = map.getContainer();
    if (x < 60 || x > w - 60 || y < 230 || y > h - 300) {
      map.easeTo({ center: [s.lon, s.lat], duration: 800, zoom: Math.min(map.getZoom() + 1, map.getZoom()) });
    }
  }, [focusHex]);

  // pulse the ring
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focusHex) return;
    let raf = 0;
    const tick = (ms: number) => {
      if (map.getLayer("focus-ring")) {
        const p = pulseAt(ms);
        map.setPaintProperty("focus-ring", "circle-radius", p.radius);
        map.setPaintProperty("focus-ring", "circle-stroke-opacity", p.opacity);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [focusHex]);

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

      // Approach centerlines: the active arrival's is amber dashed, inactive finals are muted gray.
      const arrivalActive: maplibregl.ExpressionSpecification = [
        "in",
        ["get", "runway"],
        ["literal", DEFAULT_RUNWAY_CONFIG.arrivals],
      ];
      map.addSource("approach-paths", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "approach-paths-line",
        type: "line",
        source: "approach-paths",
        paint: {
          "line-color": ["case", arrivalActive, AMBER, MUTED_GRAY],
          "line-width": 1.5,
          "line-opacity": ["case", arrivalActive, 0.9, 0.3],
          "line-dasharray": [3, 3],
        },
      });

      // Protected volumes carry a computed `state` (see runwayStyle.ts); red only for alerted ones.
      map.addSource("protected-volumes", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "protected-volumes-arrival-fill",
        type: "fill",
        source: "protected-volumes",
        filter: ["==", ["get", "state"], "active-arrival"],
        paint: { "fill-color": AMBER, "fill-opacity": 0.22 },
      });
      map.addLayer({
        id: "protected-volumes-arrival-outline",
        type: "line",
        source: "protected-volumes",
        filter: ["==", ["get", "state"], "active-arrival"],
        paint: { "line-color": AMBER, "line-width": 1, "line-opacity": 0.55 },
      });
      map.addLayer({
        id: "protected-volumes-departure-outline",
        type: "line",
        source: "protected-volumes",
        filter: ["==", ["get", "state"], "active-departure"],
        paint: { "line-color": MUTED_GRAY, "line-width": 1, "line-opacity": 0.5, "line-dasharray": [3, 3] },
      });
      map.addLayer({
        id: "protected-volumes-inactive-outline",
        type: "line",
        source: "protected-volumes",
        filter: ["==", ["get", "state"], "inactive"],
        paint: { "line-color": MUTED_GRAY, "line-width": 1, "line-opacity": 0.22 },
      });
      map.addLayer({
        id: "protected-volumes-alert-fill",
        type: "fill",
        source: "protected-volumes",
        filter: ["==", ["get", "state"], "alert"],
        paint: { "fill-color": "#ff3b3b", "fill-opacity": 0.14 },
      });
      map.addLayer({
        id: "protected-volumes-alert-outline",
        type: "line",
        source: "protected-volumes",
        filter: ["==", ["get", "state"], "alert"],
        paint: { "line-color": "#ff3b3b", "line-width": 1.75, "line-opacity": 0.8 },
      });

      // Runway pavement: light-gray strips, ~150 ft wide at real scale (width doubles per zoom
      // level), with a floor so they stay visible when zoomed out.
      map.addSource("runways", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "runways-line",
        type: "line",
        source: "runways",
        layout: { "line-cap": "butt" },
        paint: {
          "line-color": RUNWAY_GRAY,
          "line-width": ["interpolate", ["exponential", 2], ["zoom"], 9, 3, 11, 5, 14, 11, 16, 28],
        },
      });
      map.addSource("map-labels", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "runway-label",
        type: "symbol",
        source: "map-labels",
        filter: ["==", ["get", "kind"], "runway"],
        layout: {
          "text-field": ["get", "text"],
          "text-size": 11,
          "text-offset": [-2.2, 2.2],
          "text-anchor": "top-right",
          "text-allow-overlap": true,
        },
        paint: { "text-color": "#e6edf3", "text-halo-color": "#0a0e14", "text-halo-width": 1.2 },
      });
      map.addLayer({
        id: "arrival-label",
        type: "symbol",
        source: "map-labels",
        filter: ["==", ["get", "kind"], "arrival"],
        layout: {
          "text-field": ["get", "text"],
          "text-size": 12,
          "text-anchor": "left",
          "text-offset": [1.2, 0],
          "text-allow-overlap": true,
        },
        paint: { "text-color": AMBER, "text-halo-color": "#0a0e14", "text-halo-width": 1.2 },
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

      // Focused aircraft: pulsing ring (radius animated in an rAF loop) and a callout above it,
      // both above every other aircraft layer.
      map.addSource("focus", { type: "geojson", data: emptyFC() });
      map.addLayer({
        id: "focus-ring",
        type: "circle",
        source: "focus",
        paint: {
          "circle-radius": 24,
          "circle-color": ["get", "color"],
          "circle-opacity": 0.12,
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": 3,
          "circle-stroke-opacity": 0.8,
          "circle-pitch-alignment": "map",
        },
      });
      map.addLayer({
        id: "focus-callout",
        type: "symbol",
        source: "focus",
        layout: {
          "text-field": ["get", "text"],
          "text-size": 16,
          "text-anchor": "bottom",
          "text-offset": [0, -2.4],
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: { "text-color": "#ffffff", "text-halo-color": "#0a0e14", "text-halo-width": 2.5 },
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
      if (protectedVolumesGeo) {
        const feats = (protectedVolumesGeo as GeoJSON.FeatureCollection).features;
        const allProps = feats.map((f) => (f.properties ?? {}) as { id?: string; kind?: string; runway?: string | null });
        // an alert lights up its whole logical volume (every segment of that final) red
        const alertIds = new Set(alertVolumeKey ? alertVolumeKey.split("|") : []);
        const styled: GeoJSON.FeatureCollection = {
          type: "FeatureCollection",
          features: feats.map((f, i) => ({
            ...f,
            properties: { ...f.properties, state: volumeState(allProps[i], alertIds, allProps) },
          })),
        };
        (map.getSource("protected-volumes") as maplibregl.GeoJSONSource)?.setData(styled);
      }
      if (approachPaths) {
        (map.getSource("approach-paths") as maplibregl.GeoJSONSource)?.setData(approachPaths as GeoJSON.FeatureCollection);
        const props = (approachPaths as GeoJSON.FeatureCollection).features.map(
          (f) => (f.properties ?? {}) as Record<string, number | string>,
        );
        const { lines, labels } = runwayStrips(
          props.map((p) => ({
            runway: String(p.runway),
            threshold_lat: p.threshold_lat as number,
            threshold_lon: p.threshold_lon as number,
            bearing_true: p.bearing_true as number,
          })),
        );
        (map.getSource("runways") as maplibregl.GeoJSONSource)?.setData({
          type: "FeatureCollection",
          features: lines.map((coordinates) => ({
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates },
          })),
        });
        // Only the active arrival runway is labelled: "Runway 22" at its threshold and on the amber band.
        const labelFeatures: GeoJSON.Feature[] = [];
        for (const l of labels) {
          if (!DEFAULT_RUNWAY_CONFIG.arrivals.some((r) => l.name === `Runway ${r}`)) continue;
          labelFeatures.push({
            type: "Feature",
            properties: { kind: "runway", text: l.name },
            geometry: { type: "Point", coordinates: [l.lon, l.lat] },
          });
        }
        for (const p of props) {
          if (!DEFAULT_RUNWAY_CONFIG.arrivals.includes(String(p.runway))) continue;
          // the reciprocal of the landing heading points out along the final; label 3.2 nm out
          const pt = destPoint(p.threshold_lat as number, p.threshold_lon as number, (p.bearing_true as number) + 180, 3.2);
          labelFeatures.push({
            type: "Feature",
            properties: { kind: "arrival", text: `Runway ${String(p.runway)} arrivals` },
            geometry: { type: "Point", coordinates: [pt.lon, pt.lat] },
          });
        }
        (map.getSource("map-labels") as maplibregl.GeoJSONSource)?.setData({
          type: "FeatureCollection",
          features: labelFeatures,
        });
      }
      if (referencePoints)
        (map.getSource("reference-points") as maplibregl.GeoJSONSource)?.setData(referencePoints as GeoJSON.FeatureCollection);
    };
    // layers/sources are added in the load handler; once they exist setData is safe regardless of idle state
    if (map.getSource("runways")) apply();
    else map.once("load", apply);
  }, [corridors, protectedVolumesGeo, approachPaths, referencePoints, loaded, alertVolumeKey]);

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

    const focusSnap = focusHex ? snapshots.find((s) => s.hex === focusHex) : undefined;
    (map.getSource("focus") as maplibregl.GeoJSONSource)?.setData({
      type: "FeatureCollection",
      features: focusSnap
        ? [
            {
              type: "Feature",
              properties: {
                color: focusRingColor(severityByHex.get(focusSnap.hex)),
                text: calloutText(focusSnap.reg, focusSnap.alt_ft),
              },
              geometry: { type: "Point", coordinates: [focusSnap.lon, focusSnap.lat] },
            },
          ]
        : [],
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
  }, [snapshots, alerts, currentT, seekEpoch, aircraftByHex, fixedWingByHex, focusHex]);

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
  for (const [shape, color] of ICON_COMBOS) {
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

const STATUS_ITEMS: { color: string; text: string }[] = [
  { color: SEVERITY_COLOR.advisory, text: "Blue: normal" },
  { color: SEVERITY_COLOR.caution, text: "Amber: caution" },
  { color: SEVERITY_COLOR.handoff, text: "Red: handoff to controller" },
];

const legendRow: React.CSSProperties = { display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" };
const legendItem: React.CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6 };

function MapLegend() {
  return (
    <div
      aria-label="Map legend"
      style={{
        position: "absolute",
        left: 12,
        bottom: 40,
        display: "flex",
        flexDirection: "column",
        gap: 6,
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
      <div style={legendRow}>
        {LEGEND_ITEMS.map((it) => (
          <span key={it.text} style={legendItem}>
            <span
              style={{ width: 22, height: 22, display: "inline-block" }}
              dangerouslySetInnerHTML={{ __html: iconSvg(it.shape, it.color).replace(/width="64" height="64"/, 'width="22" height="22"') }}
            />
            {it.text}
          </span>
        ))}
      </div>
      <div style={legendRow}>
        {STATUS_ITEMS.map((it) => (
          <span key={it.text} style={legendItem}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: it.color, display: "inline-block" }} />
            {it.text}
          </span>
        ))}
      </div>
      <div style={legendRow}>
        <span style={legendItem}>
          <span
            style={{
              width: 22,
              height: 12,
              display: "inline-block",
              background: "rgba(242,158,76,0.22)",
              border: `1px solid ${AMBER}`,
              borderRadius: 2,
            }}
          />
          Runway 22 arrivals
        </span>
      </div>
    </div>
  );
}
