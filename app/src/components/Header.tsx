import { usePresenterStore } from "../presenter/usePresenterStore";

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
