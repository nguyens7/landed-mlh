import "./voice.css";
import { useEffect } from "react";
import { ApprovalCard, AudioToggle, HandoffCards } from "../components/ApprovalCard";
import { decide, post } from "./api";
import { useVoiceBridge } from "./useVoiceBridge";
import { useVoiceStore } from "./useVoiceStore";

/** Mount point used by App.tsx: connects the bridge once. */
export function VoiceBridge() {
  useVoiceBridge();
  return null;
}

/** Cards that float over the map (bottom centre, above the replay controls). In presenter
 * mode the hero card already carries the handoff call, so `hideHandoff` drops the duplicate. */
export function VoiceOverlay({ hideHandoff = false }: { hideHandoff?: boolean }) {
  return (
    <div className="voice-stack">
      {!hideHandoff && <HandoffCards />}
      <ApprovalCard />
    </div>
  );
}

/** Full-width red banner while the agent is locked silent; gives the human the transmit button. */
export function EmergencyBanner() {
  const locked = useVoiceStore((s) => s.locked);
  useEffect(() => {
    document.body.classList.toggle("agent-locked", locked);
  }, [locked]);
  if (!locked) return null;
  return (
    <div className="emergency-banner" role="alert">
      <span className="emergency-title">EMERGENCY: LANDED IS LOCKED SILENT</span>
      <span className="emergency-sub">Agent transmissions are disabled. The controller owns the frequency.</span>
      <button
        className="btn btn-transmit"
        onClick={() => {
          decide("human", "human_transmit").catch(() => undefined);
        }}
      >
        TRANSMIT (controller, simulated)
      </button>
      <button
        className="btn"
        onClick={() => {
          post("/unlock", { who: "controller" }).catch(() => undefined);
        }}
      >
        Unlock agent
      </button>
    </div>
  );
}

/** Append-only audit log: every auto action, approval, edit, rejection and expiry. */
export function AuditPanel() {
  const audit = useVoiceStore((s) => s.audit);
  const rows = [...audit].reverse().slice(0, 40);
  return (
    <div className="audit-panel">
      <div className="panel-title">Audit log (append-only)</div>
      <AudioToggle />
      <div className="alert-log-rows">
        {rows.length === 0 && <div className="alert-log-empty">No agent actions yet.</div>}
        {rows.map((r, i) => (
          <div key={`${r.ts}-${i}`} className="audit-row">
            <span className="mono audit-ts">{r.ts.slice(11, 23)}</span>
            <span className={`audit-decision audit-${r.decision}`}>{r.decision}</span>
            <span className="mono audit-who">{r.who}</span>
            {r.latency_ms !== null && <span className="mono audit-lat">{r.latency_ms}ms</span>}
            <div className="audit-text">{r.proposal.spoken_text_preview || r.proposal.reason || ""}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
