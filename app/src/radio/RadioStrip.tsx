import "./radio.css";
import { useRadioStore } from "./radio";

/** Live transcript of the radio exchange: the last few lines, newest at the bottom, the one being
 * transmitted right now marked with animated bars. Pilot in magenta, Landed in blue. */
export function RadioStrip({ rows: count = 3 }: { rows?: number }) {
  const rows = useRadioStore((s) => s.rows).slice(-count);
  if (rows.length === 0) return null;
  return (
    <section className="radio-strip" aria-label="Radio transcript" aria-live="polite">
      {rows.map((r) => (
        <div key={r.id} className={`radio-row radio-${r.speaker} ${r.speaking ? "speaking" : ""}`} data-speaker={r.speaker}>
          <span className="radio-label mono">{r.label}</span>
          <span className="radio-text">{r.text}</span>
          <span className="radio-bars" aria-hidden={!r.speaking} title={r.speaking ? "transmitting" : ""}>
            <i />
            <i />
            <i />
          </span>
        </div>
      ))}
    </section>
  );
}
