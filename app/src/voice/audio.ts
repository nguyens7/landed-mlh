import { fetchAudio } from "./api";

let ctx: AudioContext | null = null;

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

/** Fetch the server's audio for an approved / policy-cleared proposal and play it through a simple
 * VHF-style band-pass (300-3400 Hz). The server refuses audio for pending or expired proposals. */
export async function playProposal(proposalId: string): Promise<void> {
  if (!ctx || ctx.state !== "running") return;
  const buf = await ctx.decodeAudioData(await fetchAudio(proposalId));
  const src = ctx.createBufferSource();
  src.buffer = buf;
  const hp = ctx.createBiquadFilter();
  hp.type = "highpass";
  hp.frequency.value = 300;
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 3400;
  src.connect(hp).connect(lp).connect(ctx.destination);
  src.start();
}
