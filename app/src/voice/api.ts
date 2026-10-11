// Talks to server/ (FastAPI). The Gemini key never reaches the browser: the server holds it.

export const SERVER: string =
  (import.meta.env.VITE_LANDED_SERVER as string | undefined) ?? "http://127.0.0.1:8787";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${SERVER}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = ((await r.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // keep statusText
    }
    throw new ApiError(r.status, detail);
  }
  return (await r.json()) as T;
}

export function decide(
  proposalId: string,
  decision: "approve" | "edit" | "reject" | "human_transmit",
  slots?: Record<string, unknown>,
) {
  return post("/decision", { proposal_id: proposalId, decision, slots, who: "controller" });
}

export async function fetchAudio(proposalId: string): Promise<ArrayBuffer> {
  const r = await fetch(`${SERVER}/tts/${proposalId}`);
  if (!r.ok) throw new ApiError(r.status, `audio unavailable (${r.status})`);
  return r.arrayBuffer();
}

export function wsUrl(): string {
  return SERVER.replace(/^http/, "ws") + "/ws";
}
