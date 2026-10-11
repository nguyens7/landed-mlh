import { useDeskStore } from "../store/useDeskStore";
import { pickProminentAlert } from "../store/prominentAlert";
import type { Alert } from "../engine/types";
import type { ReplayAircraft } from "../data/types";

/** The prominent handoff card: fires when a "handoff" severity alert is active. Shows a
 * live countdown to projected entry, the plain-English reason, and Acknowledge/Take over
 * (UI-only -- logs the decision with a timestamp + latency, per SPEC.md 2.1). */
export function AlertCard() {
  const alerts = useDeskStore((s) => s.alerts);
  const acknowledge = useDeskStore((s) => s.acknowledge);
  const takeOver = useDeskStore((s) => s.takeOver);
  const decisions = useDeskStore((s) => s.decisions);

  const aircraftByHex = useDeskStore((s) => s.aircraftByHex);
  const volumes = useDeskStore((s) => s.volumes);
  const dismissedId = useDeskStore((s) => s.dismissedAlertId);
  const dismissAlert = useDeskStore((s) => s.dismissAlert);

  // One prominent card at a time: the highest-severity handoff with the soonest
  // time-to-entry. Every other alert stays in the log.
  const handoff = pickProminentAlert(alerts, volumes);

  if (!handoff || handoff.id === dismissedId) return null;

  // time_to_entry_s is re-derived from the current projection every tick, so it already
  // counts down toward the aircraft's actual entry into the protected volume.
  const countdown = Math.max(0, handoff.time_to_entry_s);
  const decided = decisions.find((d) => d.alertId === handoff.id);

  return (
    <div className={`alert-card severity-${handoff.severity}`}>
      <div className="alert-card-head">
        <span className="alert-badge">HANDOFF</span>
        <span className="alert-callsign mono">{callsignLabel(handoff, aircraftByHex[handoff.aircraft.hex])}</span>
        <span className="alert-countdown mono">{countdown.toFixed(0)}s</span>
      </div>
      <p className="alert-reason">{humanize(handoff)}</p>
      {decided ? (
        <div className="alert-decided mono">
          {decided.decision === "acknowledge" ? "Acknowledged" : "Took over"} · latency{" "}
          {decided.latency_ms}ms
        </div>
      ) : (
        <div className="alert-actions">
          <button
            className="btn btn-ack"
            onClick={() => {
              acknowledge(handoff.id);
            }}
          >
            Acknowledge
          </button>
          <button
            className="btn btn-takeover"
            onClick={() => {
              takeOver(handoff.id);
              dismissAlert(handoff.id);
            }}
          >
            Take over
          </button>
        </div>
      )}
    </div>
  );
}

/** "MEDEVAC N312LM" for the medevac only; otherwise the reg plus the role guess
 * (e.g. "N98EG · tour/charter"). */
function callsignLabel(a: Alert, ac: ReplayAircraft | undefined): string {
  const reg = a.aircraft.reg;
  if (ac?.simulated || ac?.role_guess === "medevac") return `MEDEVAC ${reg}`;
  return ac?.role_guess ? `${reg} · ${ac.role_guess}` : reg;
}

function humanize(a: Alert): string {
  return a.reason;
}
