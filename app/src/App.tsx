import { useEffect, useRef } from "react";
import "./App.css";
import "./presenter/presenter.css";
import { useDeskStore } from "./store/useDeskStore";
import { MapView } from "./components/MapView";
import { ReplayControls } from "./components/ReplayControls";
import { AlertCard } from "./components/AlertCard";
import { AlertLog } from "./components/AlertLog";
import { Header } from "./components/Header";
import { HeroCard } from "./components/HeroCard";
import { PresenterRail } from "./components/PresenterRail";
import { RadioStrip } from "./radio/RadioStrip";
import { AuditPanel, EmergencyBanner, VoiceBridge, VoiceOverlay } from "./voice/VoicePanels";
import { installPresenterHotkey, usePresenterStore } from "./presenter/usePresenterStore";

export default function App() {
  const load = useDeskStore((s) => s.load);
  const loaded = useDeskStore((s) => s.loaded);
  const error = useDeskStore((s) => s.error);
  const advance = useDeskStore((s) => s.advance);
  const presenter = usePresenterStore((s) => s.on);
  const rafRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => installPresenterHotkey(), []);

  useEffect(() => {
    const tick = (now: number) => {
      if (lastFrameRef.current !== null) {
        advance(now - lastFrameRef.current);
      }
      lastFrameRef.current = now;
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [advance]);

  if (error) {
    return <div className="app-error">Failed to load replay data: {error}</div>;
  }

  return (
    <div className={`app-shell ${presenter ? "presenter" : ""}`}>
      <Header />
      <VoiceBridge />
      <EmergencyBanner />
      <div className="app-body">
        <div className="map-pane">
          {loaded && <MapView />}
          <div className="map-attribution">ADS-B data: adsb.lol (ODbL)</div>
          {presenter ? <HeroCard /> : <AlertCard />}
          {presenter && <PresenterRail />}
          <RadioStrip rows={presenter ? 3 : 2} />
          <VoiceOverlay hideHandoff={presenter} />
        </div>
        {!presenter && (
          <div className="side-pane">
            <AlertLog />
            <AuditPanel />
          </div>
        )}
      </div>
      <ReplayControls />
    </div>
  );
}
