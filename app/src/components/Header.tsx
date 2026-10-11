import { usePresenterStore } from "../presenter/usePresenterStore";
import { enableAudio } from "../voice/audio";
import { useVoiceStore } from "../voice/useVoiceStore";

/** One click unlocks browser audio for the whole radio (pilot clips, Landed's replies, squelch). */
export function SoundButton() {
  const on = useVoiceStore((s) => s.audioEnabled);
  const setOn = useVoiceStore((s) => s.setAudioEnabled);
  return (
    <button
      className={`sound-btn ${on ? "on" : "off"}`}
      data-testid="sound-btn"
      aria-pressed={on}
      aria-label="Sound on"
      disabled={on}
      onClick={() => {
        enableAudio().then(setOn);
      }}
    >
      <span className="sound-dot" />
      {on ? "Sound on" : "Sound off: click to hear the radio"}
    </button>
  );
}

export function Header() {
  const presenter = usePresenterStore((s) => s.on);
  const toggle = usePresenterStore((s) => s.toggle);
  return (
    <header className="app-header">
      <div className="app-header-title">
        <span className="app-logo">LANDED</span>
        {!presenter && <span className="app-subtitle">Helo Desk: replay</span>}
      </div>
      <div className="app-header-right">
        <SoundButton />
        <button
          className={`presenter-chip ${presenter ? "on" : ""}`}
          aria-pressed={presenter}
          title="Press P to toggle presenter mode"
          onClick={toggle}
        >
          Presenter {presenter ? "on" : "off"} <kbd>P</kbd>
        </button>
        <div className="app-header-sim-banner">SIMULATION: not for operational use</div>
      </div>
    </header>
  );
}
