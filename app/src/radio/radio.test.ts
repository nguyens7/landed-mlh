import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import { configureRadio, enqueue, resetRadio, spokenMs, useRadioStore } from "./radio";
import type { RadioItem } from "./radio";
import { JUMP_PILOT } from "./scenarioRadio";

const events: string[] = [];
let open = 0;
let maxOpen = 0;

function item(id: string, speaker: "pilot" | "landed", ms: number, heard = true): RadioItem {
  return {
    id,
    speaker,
    label: speaker === "pilot" ? "PILOT · N312LM" : "LANDED",
    text: `text of ${id}`,
    play: async () => {
      events.push(`play:${id}`);
      open++;
      maxOpen = Math.max(maxOpen, open);
      await new Promise((r) => setTimeout(r, ms));
      open--;
      events.push(`done:${id}`);
      return heard;
    },
  };
}

const waitFor = async (cond: () => boolean) => {
  for (let i = 0; i < 200 && !cond(); i++) await new Promise((r) => setTimeout(r, 5));
};

beforeEach(() => {
  resetRadio();
  events.length = 0;
  open = 0;
  maxOpen = 0;
  configureRadio({
    squelch: async () => {
      events.push("squelch");
    },
    sleep: async () => undefined,
  });
});

describe("radio queue", () => {
  it("plays the pilot before Landed, one at a time, even when Landed is queued first by a fast server", async () => {
    enqueue(item("pilot", "pilot", 30));
    enqueue(item("landed", "landed", 10));
    await waitFor(() => events.includes("done:landed"));
    expect(events.filter((e) => e.startsWith("play:"))).toEqual(["play:pilot", "play:landed"]);
    expect(events.indexOf("done:pilot")).toBeLessThan(events.indexOf("play:landed"));
    expect(maxOpen).toBe(1);
  });

  it("brackets every transmission with a squelch click", async () => {
    enqueue(item("a", "pilot", 5));
    await waitFor(() => events.includes("done:a") && events.filter((e) => e === "squelch").length === 2);
    expect(events).toEqual(["squelch", "play:a", "done:a", "squelch"]);
  });

  it("adds a labelled transcript row when a line starts and marks only the live one as speaking", async () => {
    enqueue(item("p1", "pilot", 5));
    enqueue(item("l1", "landed", 5));
    await waitFor(() => useRadioStore.getState().rows.length === 2);
    await waitFor(() => !useRadioStore.getState().rows[1].speaking);
    const rows = useRadioStore.getState().rows;
    expect(rows.map((r) => r.label)).toEqual(["PILOT · N312LM", "LANDED"]);
    expect(rows.map((r) => r.text)).toEqual(["text of p1", "text of l1"]);
    expect(rows.every((r) => !r.speaking)).toBe(true);
  });

  it("shows the live row as speaking while its audio plays", async () => {
    enqueue(item("p1", "pilot", 60));
    await waitFor(() => useRadioStore.getState().rows.length === 1);
    expect(useRadioStore.getState().rows[0].speaking).toBe(true);
  });

  it("still shows the rows in order when there is no audio, holding for the spoken time", async () => {
    const holds: number[] = [];
    configureRadio({
      sleep: async (ms) => {
        holds.push(ms);
      },
    });
    enqueue(item("p1", "pilot", 0, false));
    enqueue(item("l1", "landed", 0, false));
    await waitFor(() => events.filter((e) => e.startsWith("done:")).length === 2);
    await waitFor(() => holds.length === 2);
    expect(useRadioStore.getState().rows.map((r) => r.speaker)).toEqual(["pilot", "landed"]);
    expect(holds.every((h) => h >= 1500)).toBe(true);
  });

  it("logs the play order for verification", async () => {
    enqueue(item("p1", "pilot", 5));
    enqueue(item("l1", "landed", 5));
    await waitFor(() => useRadioStore.getState().log.filter((l) => l.event === "end").length === 2);
    const starts = useRadioStore.getState().log.filter((l) => l.event === "start").map((l) => l.speaker);
    expect(starts).toEqual(["pilot", "landed"]);
  });

  it("drops the queue on reset", async () => {
    enqueue(item("p1", "pilot", 40));
    enqueue(item("l1", "landed", 5));
    await waitFor(() => events.includes("play:p1"));
    resetRadio();
    await new Promise((r) => setTimeout(r, 80));
    expect(events).not.toContain("play:l1");
    expect(useRadioStore.getState().rows).toEqual([]);
  });
});

describe("spokenMs", () => {
  it("scales with length and is clamped", () => {
    expect(spokenMs("roger")).toBe(1500);
    expect(spokenMs("word ".repeat(100))).toBe(9000);
  });
});

describe("jump pilot call", () => {
  it("matches S2 line L1 in the scenario data", () => {
    const f = JSON.parse(readFileSync("public/data/scenarios/S2/lines.json", "utf8")) as {
      lines: { id: string; aircraft: string; text: string }[];
    };
    const l1 = f.lines.find((l) => l.id === JUMP_PILOT.line);
    expect(l1?.text).toBe(JUMP_PILOT.text);
    expect(l1?.aircraft).toBe(JUMP_PILOT.reg);
    expect(JUMP_PILOT.text).not.toContain("—");
  });
});
