const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API error ${res.status}: ${err}`);
  }
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }
  return res.json();
}

// Health
export const getAnthropicHealth = () =>
  apiFetch<{ ok: boolean; provider?: string; error?: string }>("/api/health/llm");

// Stats
export const getStats = () => apiFetch<Stats>("/api/stats");

// Runs
export const getRuns = (params?: { limit?: number; offset?: number }) => {
  const q = new URLSearchParams(params as Record<string, string>);
  return apiFetch<{ total: number; runs: Run[] }>(`/api/runs?${q}`);
};
export const getRun = (id: number) => apiFetch<Run>(`/api/runs/${id}`);
export const triggerRun = () =>
  apiFetch("/api/runs/trigger", { method: "POST" });
export const getRunFindings = (runId: number) =>
  apiFetch<Finding[]>(`/api/runs/${runId}/findings`);

// Sources
export const getSources = (agentType?: string) => {
  const q = agentType ? `?agent_type=${agentType}` : "";
  return apiFetch<Source[]>(`/api/sources${q}`);
};
export const createSource = (body: Partial<Source>) =>
  apiFetch<Source>("/api/sources", { method: "POST", body: JSON.stringify(body) });
export const updateSource = (id: number, body: Partial<Source>) =>
  apiFetch<Source>(`/api/sources/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteSource = (id: number) =>
  apiFetch(`/api/sources/${id}`, { method: "DELETE" });
export const seedDefaultSources = () =>
  apiFetch("/api/sources/seed-defaults", { method: "POST" });

// Findings
export const getFindings = (params?: Record<string, string | number>) => {
  const q = new URLSearchParams(params as Record<string, string>);
  return apiFetch<{ total: number; findings: Finding[] }>(`/api/findings?${q}`);
};
export const getFindingsStats = () =>
  apiFetch<FindingsStats>("/api/findings/stats/summary");
export const getFindingDiff = (id: number) =>
  apiFetch<{ has_diff: boolean; diff?: string[]; prev_date?: string; curr_date?: string; message?: string }>(`/api/findings/${id}/diff`);
export const getEntityHeatmap = () =>
  apiFetch<{ entities: { entity: string; counts: Record<string, number> }[]; categories: string[] }>("/api/findings/stats/entities");

// Digests
export const getDigests = () =>
  apiFetch<{ total: number; digests: Digest[] }>("/api/digests");
export const downloadDigestUrl = (id: number) =>
  `${API_BASE}/api/digests/${id}/download`;

// Types
export interface Stats {
  total_runs: number;
  total_findings: number;
  total_digests: number;
  today_findings: number;
  last_run: { id: number; status: string; started_at: string; finished_at: string | null } | null;
  last_digest: { id: number; created_at: string; email_sent: boolean } | null;
}

export interface AgentLogEntry { msg: string; status: "info" | "success" | "error"; }

export interface Run {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  triggered_by: string;
  agent_statuses: Record<string, string>;
  agent_logs: Record<string, AgentLogEntry[]>;
  finding_count: number;
  digest?: { id: number; pdf_path: string; email_sent: boolean; created_at: string };
}

export interface Finding {
  id: number;
  run_id: number;
  agent_type: string;
  title: string;
  date_detected: string;
  source_url: string;
  publisher: string | null;
  category: string | null;
  summary_short: string | null;
  summary_long?: string | null;
  why_it_matters: string | null;
  confidence: number;
  tags: string[];
  entities: string[];
  impact_score: number;
}

export interface Source {
  id: number;
  name: string;
  agent_type: string;
  urls: string[];
  rss_feeds: string[];
  keywords: string[];
  rate_limit: number;
  enabled: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface Digest {
  id: number;
  run_id: number;
  created_at: string;
  pdf_path: string | null;
  html_summary: string | null;
  recipients: string[];
  email_sent: boolean;
  email_sent_at: string | null;
  has_pdf: boolean;
}

export interface FindingsStats {
  total: number;
  by_category: Record<string, number>;
  by_agent: Record<string, number>;
  top_publishers: Record<string, number>;
}
