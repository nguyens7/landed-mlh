import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { loadProtectedVolumes, loadReplay } from "../engine/testFixtures";
import { useDeskStore } from "./useDeskStore";

type Aircraft = ReturnType<typeof loadReplay>[number];

function fixedWing(): Aircraft[] {
  const raw = readFileSync(resolve(__dirname, "../../public/data/replay/saturday_fixedwing.json"), "utf8");
  return (JSON.parse(raw) as { aircraft: Aircraft[] }).aircraft;
}

function runAt(t: number, withFixedWing: boolean) {
  const aircraft = [...loadReplay("saturday.json"), ...loadReplay("sim_medevac.json")];
  useDeskStore.setState({
    aircraftByHex: Object.fromEntries(aircraft.map((a) => [a.hex, a])),
    fixedWingByHex: withFixedWing ? Object.fromEntries(fixedWing().map((a) => [a.hex, a])) : {},
    volumes: loadProtectedVolumes(),
    windowSeconds: 900,
    conflictEntryT: 450,
  } as Partial<ReturnType<typeof useDeskStore.getState>>);
  useDeskStore.getState().seek(t);
  const { snapshots, alerts } = useDeskStore.getState();
  return { snapshots, alerts };
}

it("fixed-wing aircraft never reach the conflict engine and do not change its output", () => {
  const fw = fixedWing();
  expect(fw.length).toBeGreaterThan(0);
  const fwHexes = new Set(fw.map((a) => a.hex));

  for (const t of [200, 395, 450]) {
    const without = runAt(t, false);
    const withFw = runAt(t, true);
    expect(withFw.snapshots.some((s) => fwHexes.has(s.hex))).toBe(false);
    expect(withFw.alerts.some((a) => fwHexes.has(a.aircraft.hex))).toBe(false);
    expect(withFw.snapshots).toEqual(without.snapshots);
    expect(withFw.alerts).toEqual(without.alerts);
  }
});

it("the fixed-wing file is tagged and separate from the helicopter replay", () => {
  const heliHexes = new Set(loadReplay("saturday.json").map((a) => a.hex));
  for (const a of fixedWing()) {
    expect((a as { kind?: string }).kind).toBe("fixed_wing");
    expect(heliHexes.has(a.hex)).toBe(false);
  }
});
