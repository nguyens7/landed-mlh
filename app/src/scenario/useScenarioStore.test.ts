import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadProtectedVolumes } from "../engine/testFixtures";
import { useDeskStore } from "../store/useDeskStore";
import { emptyVoice, reduce } from "../voice/reduce";
import type { Proposal } from "../voice/types";
import { useVoiceStore } from "../voice/useVoiceStore";
import { scenarioStartT, useScenarioStore } from "./useScenarioStore";

const AIRCRAFT = [
  {
    hex: "SIM2646X",
    reg: "N2646X",
    role_guess: "medevac",
    simulated: true,
    points: [
      { t: 10, lat: 40.7, lon: -74.0, alt_ft_msl: 500, gs_kt: 90, track_deg: 0 },
      { t: 200, lat: 40.75, lon: -74.0, alt_ft_msl: 500, gs_kt: 90, track_deg: 0 },
    ],
  },
];

function pending(): Proposal {
  return {
    id: "p1",
    kind: "speak",
    tier: "approval",
    status: "pending",
    reg: "N2646X",
    template_id: "REPORT_ACK",
    slots: {},
    spoken_text_preview: "roger",
    confidence: 0.7,
    confidence_parts: {},
    reason: "",
    evidence: [],
    triggers: [],
    source: "template",
    created_at_ms: 0,
    expires_at_ms: 10000,
    audio_ready: false,
    latency_ms: null,
  } as unknown as Proposal;
}

const calls: string[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(String(url));
      return { ok: true, status: 200, statusText: "OK", json: async () => ({}) };
    }),
  );
  useDeskStore.setState({ volumes: loadProtectedVolumes() });
  useDeskStore.getState().setReplay({ aircraft: AIRCRAFT, windowSeconds: 240, scenarioId: "S1", startT: 8 });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("scenario picker state", () => {
  it("starts the clock just before the first aircraft or line", () => {
    expect(scenarioStartT(AIRCRAFT, [{ t: 12 }])).toBe(8);
    expect(scenarioStartT(AIRCRAFT, [{ t: 3 }])).toBe(1);
    expect(scenarioStartT(AIRCRAFT, [{ t: 0 }])).toBe(0);
  });

  it("reset clears alerts, proposals, the emergency lock and decisions, and pauses", async () => {
    useDeskStore.setState({
      alerts: [{ id: "a" } as never],
      alertLog: [{ id: "a" } as never],
      decisions: [{ alertId: "a" } as never],
      playing: true,
    });
    const withCard = reduce(emptyVoice, { type: "proposal", proposal: pending() }, 0);
    useVoiceStore.setState({ ...withCard, locked: true });
    expect(useVoiceStore.getState().order).toHaveLength(1);

    await useScenarioStore.getState().reset();

    const d = useDeskStore.getState();
    expect(d.alerts).toEqual([]);
    expect(d.alertLog).toEqual([]);
    expect(d.decisions).toEqual([]);
    expect(d.playing).toBe(false);
    expect(d.currentT).toBe(8);
    const v = useVoiceStore.getState();
    expect(v.order).toEqual([]);
    expect(v.entries).toEqual({});
    expect(v.locked).toBe(false);
    expect(calls).toContain("http://127.0.0.1:8787/scenario/reset");
  });

  it("reset still clears locally when the server is down", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("offline");
      }),
    );
    useVoiceStore.setState({ locked: true });
    await useScenarioStore.getState().reset();
    expect(useVoiceStore.getState().locked).toBe(false);
    expect(useScenarioStore.getState().status).toContain("reset locally");
  });

  it("select changes the scenario and the scoreboard toggles", () => {
    useScenarioStore.getState().select("S5");
    expect(useScenarioStore.getState().selectedId).toBe("S5");
    const open = useScenarioStore.getState().scoreboardOpen;
    useScenarioStore.getState().toggleScoreboard();
    expect(useScenarioStore.getState().scoreboardOpen).toBe(!open);
  });
});
