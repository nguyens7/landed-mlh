import { useDeskStore } from "../store/useDeskStore";

export function AlertLog() {
  const alertLog = useDeskStore((s) => s.alertLog);
  const decisions = useDeskStore((s) => s.decisions);

  const rows = [...alertLog].reverse();

  return (
    <div className="alert-log">
      <div className="panel-title">Alert log</div>
      <div className="alert-log-rows">
        {rows.length === 0 && <div className="alert-log-empty">No alerts yet.</div>}
        {rows.map((a) => {
          const decision = decisions.find((d) => d.alertId === a.id);
          return (
            <div key={a.id} className={`alert-log-row severity-${a.severity}`}>
              <span className={`sev-dot sev-${a.severity}`} />
              <span className="mono alert-log-time">{fmt(a.first_seen_t)}</span>
              <span className="alert-log-reg mono">{a.aircraft.reg}</span>
              <span className="alert-log-sev">{a.severity}</span>
              <span className="alert-log-conf mono">{a.confidence.toFixed(2)}</span>
              {decision && (
                <span className="alert-log-decision mono">
                  {decision.decision} ({decision.latency_ms}ms)
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function fmt(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
