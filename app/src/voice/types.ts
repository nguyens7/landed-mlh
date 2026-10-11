// Wire types shared with server/ (FastAPI). SIMULATION ONLY: nothing here reaches a real frequency.

export type Tier = "auto" | "approval" | "handoff" | "emergency" | "suppressed";
export type Status =
  | "auto_spoken"
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "handoff_spoken"
  | "suppressed"
  | "done";

export interface Proposal {
  id: string;
  kind: "speak" | "notify_ops";
  tier: Tier;
  status: Status;
  reg: string | null;
  template_id: string | null;
  slots: Record<string, string | number | null>;
  spoken_text_preview: string;
  confidence: number;
  confidence_parts: Record<string, number | null>;
  reason: string;
  evidence: string[];
  triggers: string[];
  heard: string;
  created_at_ms: number;
  expires_at_ms: number | null;
  audio_ready: boolean;
  latency_ms: number | null;
  source: string;
  router?: RouterInfo | null;
}

/** Advisory router output attached to a proposal (agent/landed_agent/router.py). Never authorizes anything. */
export interface RouterInfo {
  label: string;
  probabilities: Record<string, number>;
  attention_p: number;
  provider: string;
  model: string;
  latency_ms: number;
  abstained: boolean;
  reason: string;
  /** shadow = logged only, the tier is unchanged; enforce = may make the decision more cautious. */
  mode?: "shadow" | "enforce";
}

/** "Router: needs review 0.91 (OpenAI Decisions, gpt-6-luna)" or "Router abstained: timeout". */
export function routerLine(r: RouterInfo | null | undefined): string | null {
  if (!r) return null;
  const shadow = r.mode === "shadow" ? " [shadow]" : "";
  if (r.abstained) return `Router abstained: ${r.reason}${shadow}`;
  const p = r.probabilities[r.label] ?? 0;
  return `Router: ${r.label.replace(/_/g, " ")} ${p.toFixed(2)} (${r.provider}, ${r.model})${shadow}`;
}

export interface AuditEntry {
  ts: string;
  proposal: Partial<Proposal> & { event?: string };
  decision: string;
  who: string;
  latency_ms: number | null;
}

export type ServerEvent =
  | { type: "snapshot"; locked: boolean; roster: string[]; proposals: Proposal[]; audit: AuditEntry[] }
  | { type: "proposal"; proposal: Proposal }
  | { type: "expired"; id: string }
  | { type: "lock"; locked: boolean }
  | { type: "audit"; entry: AuditEntry }
  | { type: "roster"; roster: string[] };
