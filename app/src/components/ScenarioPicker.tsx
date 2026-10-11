import { useEffect } from "react";
import { useScenarioStore } from "../scenario/useScenarioStore";
import "../scenario/scenario.css";

const DEFAULT_SCENARIOS = ["S1", "S2", "S3A", "S3B", "S4", "S5", "S6"];

export function ScoreboardPanel() {
  const rows = useScenarioStore((s) => s.scoreboard);
  const open = useScenarioStore((s) => s.scoreboardOpen);
  if (!open) return null;
  return (
    <div className="scoreboard-panel" role="region" aria-label="Scenario scoreboard">
      <div className="panel-title">
        Scoreboard <span className="sim-tag">SIM</span>
      </div>
      {rows.length === 0 && <div className="alert-log-empty">No scoreboard data.</div>}
      {rows.map((r) => (
        <div key={r.id} className="scoreboard-row">
          <span className="mono scoreboard-id">{r.id}</span>
          <span className={`scoreboard-status ${r.three_of_three ? "ok" : "bad"}`}>
            {r.three_of_three ? `${r.repeat}/${r.repeat}` : "not stable"}
          </span>
          <span className="mono scoreboard-count">
            {r.tally.pass}/{r.tally.total} pass{r.tally.gap ? `, ${r.tally.gap} gap` : ""}
          </span>
          <span className="scoreboard-title">{r.title}</span>
        </div>
      ))}
    </div>
  );
}

export function ScenarioPicker() {
  const scenarios = useScenarioStore((s) => s.scenarios);
  const selectedId = useScenarioStore((s) => s.selectedId);
  const status = useScenarioStore((s) => s.status);
  const open = useScenarioStore((s) => s.scoreboardOpen);
  const { init, select, play, reset, toggleScoreboard } = useScenarioStore.getState();

  useEffect(() => {
    init();
  }, [init]);

  const options = scenarios.length
    ? scenarios
    : DEFAULT_SCENARIOS.map((id) => ({ id, title: "", window_s: 0 }));

  return (
    <div className="scenario-picker">
      <span className="sim-tag">SIM</span>
      <select
        className="scenario-select"
        aria-label="Scenario"
        value={selectedId}
        onChange={(e) => select(e.target.value)}
      >
        {options.map((s) => (
          <option key={s.id} value={s.id}>
            {s.title ? `${s.id}: ${s.title}` : s.id}
          </option>
        ))}
      </select>
      <button className="btn btn-primary" onClick={() => void play()}>
        Play scenario
      </button>
      <button className="btn" onClick={() => void reset()}>
        Reset
      </button>
      <button className={`btn ${open ? "btn-speed active" : ""}`} onClick={toggleScoreboard}>
        Scoreboard
      </button>
      {status && <span className="mono scenario-status">{status}</span>}
      <ScoreboardPanel />
    </div>
  );
}
