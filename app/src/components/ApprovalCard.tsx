import { useState } from "react";
import { enableAudio } from "../voice/audio";
import { ARM_MS, isArmed, remainingMs } from "../voice/keys";
import { activeCard, localExpiry } from "../voice/reduce";
import { runAction } from "../voice/useVoiceBridge";
import { decide } from "../voice/api";
import { useVoiceStore } from "../voice/useVoiceStore";
import { useDeskStore } from "../store/useDeskStore";
import { routerLine, type Proposal } from "../voice/types";

/** The approval card: the exact words that will be spoken, why, how sure, and a 10 s expiry bar.
 * Keys A / E / R are bound to this one card only, and only after the 1 s arm delay. An expired card
 * is dropped, never sent. SIMULATION: nothing is transmitted on a real frequency. */
export function ApprovalCard() {
  const v = useVoiceStore();
  const card = activeCard(v);
  const entry = card ? v.entries[card.id] : undefined;
  const queued = v.order.filter((id) => id !== v.activeId && v.entries[id]?.p.status === "pending").length;
  if (!card || !entry) return null;
  const p = entry.p;
  const now = v.now;
  const armed = isArmed(card, now);
  const total = p.expires_at_ms !== null ? p.expires_at_ms - p.created_at_ms : 10_000;
  const left = remainingMs({ expiresAt: localExpiry(entry) }, now);
  const editing = v.editingId === p.id;
  const spokenBy =p.kind === "notify_ops" ? "SIMULATED OPS CALL" : "WILL SAY ON SIM FREQUENCY";

  return (
    <div className="approval-card" data-proposal-id={p.id}>
      <div className="approval-head">
        <span className="approval-badge">APPROVAL</span>
        <span className="alert-callsign mono">{p.reg ? `MEDEVAC ${p.reg}` : "UNIDENTIFIED"}</span>
        {p.kind === "speak" && (
          <span className="approval-conf mono" title={confTitle(p)}>
            conf {p.confidence.toFixed(2)}
          </span>
        )}
        <span className="approval-count mono">{(left / 1000).toFixed(1)}s</span>
      </div>
      <div className="approval-expiry" aria-label="expiry">
        <div className="approval-expiry-fill" style={{ width: `${Math.min(100, (left / total) * 100)}%` }} />
      </div>
      {p.heard && <div className="approval-heard mono">heard: “{p.heard}”</div>}
      <div className="approval-label">{spokenBy}</div>
      {editing ? (
        <EditForm p={p} />
      ) : (
        <blockquote className="approval-words mono">“{p.spoken_text_preview}”</blockquote>
      )}
      <LiveReason p={p} />
      <RouterLine p={p} />
      {p.evidence.length > 0 && (
        <ul className="approval-evidence">
          {p.evidence.slice(0, 4).map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
      {v.editError && <div className="approval-error mono">{v.editError}</div>}
      {!editing && (
        <div className="approval-actions">
          <button className="btn btn-approve" disabled={!armed || (v.locked && p.kind === "speak")} onClick={() => runAction("approve", p.id)}>
            <kbd>A</kbd> Approve
          </button>
          {p.kind === "speak" && (
            <button className="btn" disabled={!armed} onClick={() => runAction("edit", p.id)}>
              <kbd>E</kbd> Edit
            </button>
          )}
          <button className="btn btn-takeover" disabled={!armed} onClick={() => runAction("reject", p.id)}>
            <kbd>R</kbd> Reject / take over
          </button>
          <span className="approval-arm mono">{armed ? "armed" : `arming ${Math.ceil((ARM_MS - (now - card.shownAt)) / 100) / 10}s`}</span>
        </div>
      )}
      {queued > 0 && <div className="approval-queue mono">+{queued} more waiting; keys act on this card only</div>}
    </div>
  );
}

/** The engine alert's reason, read live from the desk store so the time-to-entry matches the
 * alert card's countdown. Falls back to the proposal's own reason (no live alert, e.g. after the
 * aircraft left the volume). The leading "REG: " is dropped; the card header already names it. */
function LiveReason({ p }: { p: Proposal }) {
  const live = useDeskStore((s) => s.alerts.find((a) => a.severity === "handoff" && a.aircraft.reg === p.reg));
  // Engine-alert proposals (source "policy") carry the alert's reason; show the live copy of it.
  const text = live && p.source === "policy" && p.triggers.includes("path_protected_volume") ? live.reason : p.reason;
  const shown = p.reg && text.startsWith(`${p.reg}: `) ? text.slice(p.reg.length + 2) : text;
  return <p className="alert-reason">{shown}</p>;
}

/** One advisory line: what the typed router said, or why it abstained. Shown only when a router ran. */
function RouterLine({ p }: { p: Proposal }) {
  const line = routerLine(p.router);
  return line ? <div className="approval-router mono">{line}</div> : null;
}

function confTitle(p: Proposal): string {
  return Object.entries(p.confidence_parts)
    .map(([k, val]) => `${k} ${val === null ? "n/a" : val.toFixed(2)}`)
    .join(" x ");
}

function EditForm({ p }: { p: Proposal }) {
  const [vals, setVals] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(p.slots).map(([k, val]) => [k, String(val ?? "")])),
  );
  const setEditing = useVoiceStore((s) => s.setEditing);
  const setEditError = useVoiceStore((s) => s.setEditError);

  const save = () => {
    const slots: Record<string, unknown> = {};
    for (const [k, s] of Object.entries(vals)) {
      if (s === "") continue;
      slots[k] = s !== "" && !Number.isNaN(Number(s)) && k !== "reg" ? Number(s) : s;
    }
    decide(p.id, "edit", slots)
      .then(() => setEditing(null))
      .catch((e: unknown) => setEditError(e instanceof Error ? e.message : String(e)));
  };

  return (
    <form
      className="approval-edit"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") setEditing(null);
      }}
    >
      {Object.keys(vals).map((k) => (
        <label key={k} className="approval-edit-row mono">
          <span>{k}</span>
          <input value={vals[k]} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} autoFocus={k === Object.keys(vals)[0]} />
        </label>
      ))}
      <div className="approval-actions">
        <button className="btn btn-approve" type="submit">
          Save (Enter)
        </button>
        <button className="btn" type="button" onClick={() => setEditing(null)}>
          Cancel (Esc)
        </button>
      </div>
      <div className="approval-hint">Server re-validates every slot; the preview is re-rendered from the template.</div>
    </form>
  );
}

/** Policy-handled handoffs (STANDBY_HANDOFF already spoken) that need the human: shown until acknowledged. */
export function HandoffCards() {
  const v = useVoiceStore();
  const [done, setDone] = useState<Set<string>>(new Set());
  const rows = v.order
    .map((id) => v.entries[id]?.p)
    .filter((p): p is Proposal => !!p && p.status === "handoff_spoken" && p.tier === "handoff" && !done.has(p.id))
    .slice(-1);
  return (
    <>
      {rows.map((p) => (
        <div key={p.id} className="approval-card handoff-spoken">
          <div className="approval-head">
            <span className="approval-badge handoff">HANDOFF</span>
            <span className="alert-callsign mono">{p.reg ? `MEDEVAC ${p.reg}` : "UNIDENTIFIED"}</span>
            <span className="approval-conf mono">conf {p.confidence.toFixed(2)}</span>
          </div>
          <div className="approval-label">LANDED SAID (STANDBY)</div>
          <blockquote className="approval-words mono">“{p.spoken_text_preview}”</blockquote>
          <LiveReason p={p} />
          <RouterLine p={p} />
          <div className="approval-actions">
            <button
              className="btn btn-takeover"
              onClick={() => {
                decide(p.id, "human_transmit").catch(() => undefined);
                setDone(new Set(done).add(p.id));
              }}
            >
              Controller has it
            </button>
          </div>
        </div>
      ))}
    </>
  );
}

export function AudioToggle() {
  const enabled = useVoiceStore((s) => s.audioEnabled);
  const connected = useVoiceStore((s) => s.connected);
  const set = useVoiceStore((s) => s.setAudioEnabled);
  return (
    <div className="voice-status mono">
      <span className={`sev-dot ${connected ? "sev-advisory" : "sev-handoff"}`} /> agent {connected ? "online" : "offline"}
      <button
        className="btn"
        disabled={enabled}
        onClick={() => {
          enableAudio().then(set);
        }}
      >
        {enabled ? "Audio on" : "Enable audio"}
      </button>
    </div>
  );
}
