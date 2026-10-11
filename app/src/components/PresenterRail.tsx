import { useDeskStore } from "../store/useDeskStore";
import { useVoiceStore } from "../voice/useVoiceStore";
import { usePresenterStore } from "../presenter/usePresenterStore";
import type { AuditEntry } from "../voice/types";
import { AlertLog } from "./AlertLog";
import { AuditPanel } from "../voice/VoicePanels";

/** Presenter mode's collapsed logs: one line each for the alert log and the audit log,
 * expandable on click into the full panel. */
export function PresenterRail() {
  const alertLog = useDeskStore((s) => s.alertLog);
  const audit = useVoiceStore((s) => s.audit);
  const alertsOpen = usePresenterStore((s) => s.alertsOpen);
  const auditOpen = usePresenterStore((s) => s.auditOpen);
  const setAlertsOpen = usePresenterStore((s) => s.setAlertsOpen);
  const setAuditOpen = usePresenterStore((s) => s.setAuditOpen);

  const handoffs = alertLog.filter((a) => a.severity === "handoff").length;
  const n = alertLog.length;
  const latest = audit.length ? audit[audit.length - 1] : null;

  return (
    <aside className="presenter-rail" aria-label="Logs">
      <button
        className={`rail-chip ${alertsOpen ? "open" : ""}`}
        aria-expanded={alertsOpen}
        onClick={() => setAlertsOpen(!alertsOpen)}
      >
        <span className={`sev-dot ${handoffs ? "sev-handoff" : n ? "sev-caution" : "sev-advisory"}`} />
        <span className="rail-chip-text">{n === 0 ? "No alerts" : n === 1 ? "1 alert" : `${n} alerts`}</span>
        <span className="rail-chip-caret" aria-hidden>{alertsOpen ? "Hide" : "Show"}</span>
      </button>
      {alertsOpen && (
        <div className="rail-panel" data-testid="alerts-panel">
          <AlertLog />
        </div>
      )}
      <button
        className={`rail-chip rail-chip-audit ${auditOpen ? "open" : ""}`}
        aria-expanded={auditOpen}
        onClick={() => setAuditOpen(!auditOpen)}
      >
        <span className="rail-chip-text">{auditLine(latest)}</span>
        <span className="rail-chip-caret" aria-hidden>{auditOpen ? "Hide" : "Show"}</span>
      </button>
      {auditOpen && (
        <div className="rail-panel" data-testid="audit-panel">
          <AuditPanel />
        </div>
      )}
    </aside>
  );
}

/** The newest audit row in one line, e.g. "Landed said: ..., standby, ...". */
export function auditLine(e: AuditEntry | null): string {
  if (!e) return "Audit log: no agent actions yet";
  const words = e.proposal.spoken_text_preview || e.proposal.reason || "";
  const spoke = e.decision.includes("speak") || e.decision === "approved" || e.decision === "approve";
  if (spoke && words) return `Landed said: “${words}”`;
  const who = e.who === "agent" ? "Landed" : e.who;
  return words ? `${who}, ${e.decision.replace(/_/g, " ")}: ${words}` : `${who}, ${e.decision.replace(/_/g, " ")}`;
}
