import { create } from "zustand";
import { dropPending, emptyVoice, pickActive, reduce } from "./reduce";
import type { VoiceData } from "./reduce";
import type { ServerEvent } from "./types";

interface VoiceState extends VoiceData {
  connected: boolean;
  audioEnabled: boolean;
  editingId: string | null;
  editError: string | null;
  now: number;
  apply: (ev: ServerEvent) => void;
  tick: () => void;
  rewind: () => void;
  setConnected: (c: boolean) => void;
  setAudioEnabled: (e: boolean) => void;
  setEditing: (id: string | null) => void;
  setEditError: (e: string | null) => void;
}

export const useVoiceStore = create<VoiceState>((set, get) => ({
  ...emptyVoice,
  connected: false,
  audioEnabled: false,
  editingId: null,
  editError: null,
  now: Date.now(),
  apply: (ev) => set((s) => ({ ...reduce(s, ev, Date.now()), now: Date.now() })),
  // Re-evaluate the active card as local expiry passes (the server also pushes "expired").
  tick: () => {
    const now = Date.now();
    const s = get();
    const activeId = pickActive(s, now);
    if (activeId !== s.activeId) {
      set({ activeId, activeShownAt: now, now, editingId: activeId === s.editingId ? s.editingId : null });
    } else {
      set({ now });
    }
  },
  rewind: () => set((s) => ({ ...dropPending(s, Date.now()), editingId: null, editError: null })),
  setConnected: (connected) => set({ connected }),
  setAudioEnabled: (audioEnabled) => set({ audioEnabled }),
  setEditing: (editingId) => set({ editingId, editError: null }),
  setEditError: (editError) => set({ editError }),
}));
