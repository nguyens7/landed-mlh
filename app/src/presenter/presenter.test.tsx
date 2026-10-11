// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { installPresenterHotkey, isPresenterToggleKey, usePresenterStore } from "./usePresenterStore";
import { detail, headline, pickHeroAlert, statusWord } from "./story";
import { Header } from "../components/Header";
import { PresenterRail, auditLine } from "../components/PresenterRail";
import { useDeskStore } from "../store/useDeskStore";
import { useVoiceStore } from "../voice/useVoiceStore";
import type { Alert, ProtectedVolume } from "../engine/types";
import type { ReplayAircraft } from "../data/types";

const alert = (over: Partial<Alert> = {}): Alert => ({
  id: "a1",
  aircraft: { hex: "abc", reg: "N312LM" },
  volume_id: "v22",
  severity: "handoff",
  confidence: 0.97,
  reason: "N312LM: Projected path crosses LGA Rwy 22 final in 77 s.",
  time_to_entry_s: 77,
  entry_point: { lat: 40.8, lon: -73.9 },
  entry_alt_ft: 600,
  first_seen_t: 365,
  last_seen_t: 398,
  ...over,
});

beforeEach(() => {
  usePresenterStore.setState({ on: true, alertsOpen: false, auditOpen: false });
  useDeskStore.setState({ alertLog: [], decisions: [] });
  useVoiceStore.setState({ audit: [] });
});
afterEach(cleanup);

describe("presenter mode toggle", () => {
  it("is on by default", () => {
    expect(usePresenterStore.getInitialState().on).toBe(true);
    render(<Header />);
    expect(screen.getByRole("button", { name: /presenter on/i })).toHaveProperty("ariaPressed", "true");
  });

  it("P toggles it, and P typed into a field does not", () => {
    const uninstall = installPresenterHotkey();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "p" }));
    });
    expect(usePresenterStore.getState().on).toBe(false);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "P" }));
    });
    expect(usePresenterStore.getState().on).toBe(true);
    uninstall();

    const input = document.createElement("input");
    expect(isPresenterToggleKey({ key: "p", metaKey: false, ctrlKey: false, altKey: false, target: input })).toBe(false);
    expect(isPresenterToggleKey({ key: "p", metaKey: true, ctrlKey: false, altKey: false, target: null })).toBe(false);
  });

  it("the header chip shows and flips the state", () => {
    render(<Header />);
    fireEvent.click(screen.getByRole("button", { name: /presenter on/i }));
    expect(usePresenterStore.getState().on).toBe(false);
    expect(screen.getByRole("button", { name: /presenter off/i })).toBeTruthy();
  });
});

describe("collapsed logs", () => {
  it("show a slim count and expand on click", () => {
    useDeskStore.setState({ alertLog: [alert(), alert({ id: "a2", severity: "caution" })] });
    render(<PresenterRail />);
    const chip = screen.getByRole("button", { name: /2 alerts/i });
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByTestId("alerts-panel")).toBeNull();
    fireEvent.click(chip);
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByTestId("alerts-panel").textContent).toContain("N312LM");
  });

  it("audit collapses to its latest line and expands on click", () => {
    useVoiceStore.setState({
      audit: [
        { ts: "2026-10-11T18:14:15.842Z", decision: "proposed", who: "agent", latency_ms: null, proposal: { spoken_text_preview: "older" } },
        {
          ts: "2026-10-11T18:14:43.683Z",
          decision: "handoff_speak",
          who: "agent",
          latency_ms: 1,
          proposal: { spoken_text_preview: "MEDEVAC Three One Two Lima Mike, standby" },
        },
      ],
    });
    render(<PresenterRail />);
    const chip = screen.getByRole("button", { name: /Landed said: .*standby/ });
    fireEvent.click(chip);
    expect(screen.getByTestId("audit-panel").textContent).toContain("older");
  });

  it("audit line falls back when empty", () => {
    expect(auditLine(null)).toMatch(/no agent actions yet/);
  });
});

describe("hero story wording", () => {
  const vol = (kind: ProtectedVolume["kind"]) => ({ id: "v22", kind }) as ProtectedVolume;
  const sim = { simulated: true, role_guess: "medevac" } as ReplayAircraft;

  it("uses plain status words", () => {
    expect(statusWord("handoff")).toBe("Handed to controller");
    expect(statusWord("caution")).toBe("Caution");
    expect(statusWord(null)).toBe("Normal");
  });

  it("writes a short headline and keeps the engine reason as detail", () => {
    expect(headline(alert(), sim, vol("approach"))).toBe("Medevac heading into LaGuardia arrivals");
    expect(headline(alert({ aircraft: { hex: "x", reg: "N98EG" } }), undefined, vol("departure"))).toBe(
      "Helicopter N98EG heading into LaGuardia departures",
    );
    expect(detail(alert())).toBe("Projected path crosses LGA Rwy 22 final in 77 s.");
  });

  it("prefers the handoff, else the soonest caution", () => {
    const c1 = alert({ id: "c1", severity: "caution", time_to_entry_s: 50 });
    const c2 = alert({ id: "c2", severity: "caution", time_to_entry_s: 20 });
    expect(pickHeroAlert(alert(), [c1, c2])?.id).toBe("a1");
    expect(pickHeroAlert(null, [c1, c2])?.id).toBe("c2");
    expect(pickHeroAlert(null, [])).toBeNull();
  });
});
