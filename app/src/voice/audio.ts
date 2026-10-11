import { fetchAudio } from "./api";

let ctx: AudioContext | null = null;
let active: AudioBufferSourceNode | null = null;

/** Must be called from a user gesture once (browser autoplay policy). */
export async function enableAudio(): Promise<boolean> {
  try {
    ctx ??= new AudioContext();
    if (ctx.state !== "running") await ctx.resume();
    return ctx.state === "running";
  } catch {
    return false;
  }
}

export function audioRunning(): boolean {
  return ctx !== null && ctx.state === "running";
}

/** Stop whatever clip is playing right now (its play promise resolves). */
export function stopAudio(): void {
  try {
    active?.stop();
  } catch {
    // already stopped
  }
}

/** Decode and play one clip; resolves true when it finished, false when audio is off or the clip is bad.
 * `vhf` adds a 300-3400 Hz band-pass (agent speech); pilot clips are already radio-filtered by the build. */
export async function playBuffer(data: ArrayBuffer, vhf: boolean): Promise<boolean> {
  if (!ctx || ctx.state !== "running") return false;
  const c = ctx;
  let buf: AudioBuffer;
  try {
    buf = await c.decodeAudioData(data);
  } catch {
    return false;
  }
  return new Promise<boolean>((resolve) => {
    const src = c.createBufferSource();
    src.buffer = buf;
    if (vhf) {
      const hp = c.createBiquadFilter();
      hp.type = "highpass";
      hp.frequency.value = 300;
      const lp = c.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.value = 3400;
      src.connect(hp).connect(lp).connect(c.destination);
    } else {
      src.connect(c.destination);
    }
    src.onended = () => {
      if (active === src) active = null;
      resolve(true);
    };
    active = src;
    src.start();
  });
}

/** Fetch the server's audio for an approved / policy-cleared proposal and play it through a simple
 * VHF-style band-pass. The server refuses audio for pending or expired proposals. */
export async function playProposal(proposalId: string): Promise<boolean> {
  if (!audioRunning()) return false;
  try {
    return await playBuffer(await fetchAudio(proposalId), true);
  } catch {
    return false;
  }
}

/** Radio squelch: a short filtered noise burst with a click, synthesized (no files).
 * Resolves when it has finished so the queue can keep transmissions apart. */
export function squelch(): Promise<void> {
  if (!ctx || ctx.state !== "running") return Promise.resolve();
  const c = ctx;
  const dur = 0.09;
  const n = Math.floor(c.sampleRate * dur);
  const noise = c.createBuffer(1, n, c.sampleRate);
  const d = noise.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.exp((-i / n) * 5);
  d[0] = 1; // the click
  const src = c.createBufferSource();
  src.buffer = noise;
  const bp = c.createBiquadFilter();
  bp.type = "bandpass";
  bp.frequency.value = 2200;
  bp.Q.value = 0.7;
  const g = c.createGain();
  g.gain.value = 0.35;
  src.connect(bp).connect(g).connect(c.destination);
  return new Promise((resolve) => {
    src.onended = () => resolve();
    src.start();
  });
}
