import { expect, it } from "vitest";
import type { Alert } from "../engine/types";
import { loadProtectedVolumes, loadReplay } from "../engine/testFixtures";
import { useDeskStore } from "./useDeskStore";

it("Jump to conflict lands with the medevac handoff already active", () => {
  const aircraft = [...loadReplay("saturday.json"), ...loadReplay("sim_medevac.json")];
  useDeskStore.setState({
    aircraftByHex: Object.fromEntries(aircraft.map((a) => [a.hex, a])),
    volumes: loadProtectedVolumes(),
    windowSeconds: 900,
    conflictEntryT: 450,
  } as Partial<ReturnType<typeof useDeskStore.getState>>);
  useDeskStore.getState().jumpToConflict();
  const medevac = (useDeskStore.getState().alerts as Alert[]).find((a) => a.aircraft.reg === "N312LM");
  expect(medevac?.severity).toBe("handoff");
  expect(medevac?.time_to_entry_s).toBeGreaterThan(45);
});
