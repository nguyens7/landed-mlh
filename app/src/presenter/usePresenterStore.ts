// Presenter mode: a demo-first layout with one hero card and collapsed logs. Default ON;
// the P key toggles it. Out of presenter mode the full console is unchanged.
import { create } from "zustand";

interface PresenterState {
  on: boolean;
  alertsOpen: boolean;
  auditOpen: boolean;
  toggle: () => void;
  setOn: (on: boolean) => void;
  setAlertsOpen: (open: boolean) => void;
  setAuditOpen: (open: boolean) => void;
}

export const usePresenterStore = create<PresenterState>((set) => ({
  on: true,
  alertsOpen: false,
  auditOpen: false,
  toggle: () => set((s) => ({ on: !s.on })),
  setOn: (on) => set({ on }),
  setAlertsOpen: (alertsOpen) => set({ alertsOpen }),
  setAuditOpen: (auditOpen) => set({ auditOpen }),
}));

/** True when a key press should toggle presenter mode: a bare P outside any text field. */
export function isPresenterToggleKey(e: Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "altKey" | "target">): boolean {
  if (e.key !== "p" && e.key !== "P") return false;
  if (e.metaKey || e.ctrlKey || e.altKey) return false;
  const el = e.target as HTMLElement | null;
  const tag = el?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return false;
  return true;
}

/** Installs the global P listener. Returns the cleanup function. */
export function installPresenterHotkey(target: Window = window): () => void {
  const onKey = (e: KeyboardEvent) => {
    if (isPresenterToggleKey(e)) usePresenterStore.getState().toggle();
  };
  target.addEventListener("keydown", onKey);
  return () => target.removeEventListener("keydown", onKey);
}
