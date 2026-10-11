import { useEffect, useState, type CSSProperties } from "react";
import { HELI_COLORS, MEDEVAC_COLOR, iconDataUrl } from "./mapIcons";
import { useDeskStore } from "../store/useDeskStore";
import { pickProminentAlert } from "../store/prominentAlert";
import { useVoiceStore } from "../voice/useVoiceStore";
import { decide } from "../voice/api";
import type { Proposal } from "../voice/types";
import { detail, headline, pickHeroAlert, statusWord, toneOf } from "../presenter/story";

/** Presenter mode's single focal point. A handoff (or, failing that, a caution) is shown as
 * one card: plain status word, a one-line headline, a large countdown, the engine's exact
 * reason in smaller text, and what Landed told the pilot. With nothing active it says what
 * the desk is watching and what to press. Replaces AlertCard and the voice handoff card. */
export function HeroCard() {
  const alerts = useDeskStore((s) => s.alerts);
  const volumes = useDeskStore((s) => s.volumes);
  const aircraftByHex = useDeskStore((s) => s.aircraftByHex);
  const decisions = useDeskStore((s) => s.decisions);
  const dismissedId = useDeskStore((s) => s.dismissedAlertId);
  const acknowledge = useDeskStore((s) => s.acknowledge);
  const takeOver = useDeskStore((s) => s.takeOver);
  const dismissAlert = useDeskStore((s) => s.dismissAlert);
  const voice = useVoiceStore();
  const [handled, setHandled] = useState<Set<string>>(new Set());

  const picked = pickHeroAlert(pickProminentAlert(alerts, volumes), alerts);
  const alert = picked && picked.id !== dismissedId ? picked : null;
  const focusHex = alert ? alert.aircraft.hex : null;

  // Point the map at the aircraft this card is about (ring + callout on the map side).
  useEffect(() => {
    useDeskStore.getState().setFocusedHex(focusHex);
  }, [focusHex]);
  useEffect(() => () => useDeskStore.getState().setFocusedHex(null), []);

  if (!alert) {
    return (
      <section className="hero-card tone-normal hero-idle" aria-label="Status">
        <div className="hero-status">
          <span className="hero-dot" />
          {statusWord(null)}
        </div>
        <h2 className="hero-headline">Watching helicopter traffic around LaGuardia</h2>
        <p className="hero-detail">Press Jump to conflict to replay the medevac handoff.</p>
      </section>
    );
  }

  const ac = aircraftByHex[alert.aircraft.hex];
  const volume = volumes.find((v) => v.id === alert.volume_id);
  const tone = toneOf(alert.severity);
  const countdown = Math.max(0, alert.time_to_entry_s).toFixed(0);
  const decided = decisions.find((d) => d.alertId === alert.id);
  const isSim = !!ac?.simulated;
  const isMedevac = isSim || ac?.role_guess === "medevac";
  // Same color as the map's ring on this aircraft: magenta for the SIM medevac, else severity.
  const chipColor = isMedevac ? MEDEVAC_COLOR : tone === "handoff" ? HELI_COLORS[2] : tone === "caution" ? HELI_COLORS[1] : HELI_COLORS[0];
  const spoken = latestSpokenHandoff(voice.order, voice.entries, alert.aircraft.reg);

  return (
    <section className={`hero-card tone-${tone}`} aria-label="Handoff" data-alert-id={alert.id}>
      <div className="hero-top">
        <div className="hero-status">
          <span className="hero-dot" />
          {statusWord(alert.severity)}
        </div>
        <CallsignChip reg={alert.aircraft.reg} medevac={isMedevac} sim={isSim} color={chipColor} />
      </div>
      <div className="hero-main">
        <h2 className="hero-headline">{headline(alert, ac, volume)}</h2>
        <div className="hero-countdown" aria-label={`${countdown} seconds to entry`}>
          <span className="hero-count mono">{countdown}</span>
          <span className="hero-count-unit">s to entry</span>
        </div>
      </div>
      <p className="hero-detail">{detail(alert)}</p>
      {spoken && (
        <p className="hero-said">
          <span className="hero-said-label">Landed said to the pilot</span>
          <span className="hero-said-words">“{spoken.spoken_text_preview}”</span>
        </p>
      )}
      {decided ? (
        <div className="hero-decided">
          {decided.decision === "acknowledge" ? "Acknowledged" : "Took over"} in {decided.latency_ms} ms
        </div>
      ) : (
        <div className="hero-actions">
          <button className="btn btn-ack" onClick={() => acknowledge(alert.id)}>
            Acknowledge
          </button>
          <button
            className="btn btn-takeover"
            onClick={() => {
              takeOver(alert.id);
              dismissAlert(alert.id);
            }}
          >
            Take over
          </button>
          {spoken && !handled.has(spoken.id) && (
            <button
              className="btn"
              onClick={() => {
                decide(spoken.id, "human_transmit").catch(() => undefined);
                setHandled(new Set(handled).add(spoken.id));
              }}
            >
              Controller has it
            </button>
          )}
        </div>
      )}
    </section>
  );
}

/** The aircraft's map icon and registration in the map ring's color, so the eye links the
 * card to the ringed aircraft on the map. */
function CallsignChip({ reg, medevac, sim, color }: { reg: string; medevac: boolean; sim: boolean; color: string }) {
  return (
    <span className="hero-chip" style={{ "--chip": color } as CSSProperties}>
      <img className="hero-chip-icon" src={iconDataUrl(medevac ? "medevac" : "heli", color)} alt="" />
      <span className="mono hero-chip-reg">{reg}</span>
      {sim && <span className="hero-chip-tag">SIM medevac</span>}
    </span>
  );
}

/** The newest "standby, controller will be with you" call Landed made for this aircraft. */
function latestSpokenHandoff(
  order: string[],
  entries: Record<string, { p: Proposal } | undefined>,
  reg: string,
): Proposal | null {
  for (let i = order.length - 1; i >= 0; i--) {
    const p = entries[order[i]]?.p;
    if (p && p.status === "handoff_spoken" && p.tier === "handoff" && p.reg === reg) return p;
  }
  return null;
}
