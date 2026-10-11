import { useDeskStore, type Speed } from "../store/useDeskStore";
import { ScenarioPicker } from "./ScenarioPicker";

function fmtClock(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function ReplayControls() {
  const playing = useDeskStore((s) => s.playing);
  const speed = useDeskStore((s) => s.speed);
  const currentT = useDeskStore((s) => s.currentT);
  const windowSeconds = useDeskStore((s) => s.windowSeconds);
  const play = useDeskStore((s) => s.play);
  const pause = useDeskStore((s) => s.pause);
  const setSpeed = useDeskStore((s) => s.setSpeed);
  const seek = useDeskStore((s) => s.seek);
  const jumpToConflict = useDeskStore((s) => s.jumpToConflict);

  return (
    <div className="replay-controls">
      <button className="btn btn-primary btn-play" onClick={() => (playing ? pause() : play())}>
        {playing ? "Pause" : "Play"}
      </button>
      {/* display: contents outside presenter mode, so the full console layout is unchanged */}
      <div className="replay-compact">
      <div className="speed-group">
        {([1, 4, 16] as Speed[]).map((sp) => (
          <button key={sp} className={`btn btn-speed ${speed === sp ? "active" : ""}`} onClick={() => setSpeed(sp)}>
            {sp}×
          </button>
        ))}
      </div>
      <span className="mono clock">
        {fmtClock(currentT)} / {fmtClock(windowSeconds)}
      </span>
      <input
        className="scrubber"
        type="range"
        min={0}
        max={windowSeconds}
        step={1}
        value={currentT}
        aria-label="Replay position"
        onChange={(e) => seek(Number(e.target.value))}
      />
      </div>
      <button className="btn btn-conflict" onClick={jumpToConflict}>
        Jump to conflict
      </button>
      <ScenarioPicker />
    </div>
  );
}
