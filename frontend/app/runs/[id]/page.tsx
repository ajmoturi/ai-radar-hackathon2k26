"use client";
import useSWR from "swr";
import Link from "next/link";
import { use } from "react";
import { getRun, getRunFindings, downloadDigestUrl } from "@/lib/api";
import type { Run, Finding, AgentLogEntry } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-green-50 text-green-700 border-green-200",
  running: "bg-blue-50 text-blue-700 border-blue-200",
  partial: "bg-yellow-50 text-yellow-700 border-yellow-200",
  failed: "bg-red-50 text-red-700 border-red-200",
};

const AGENT_LABELS: Record<string, string> = {
  competitor: "Competitor Watcher",
  model_provider: "Model Provider Watcher",
  research: "Research Scout",
  hf_benchmark: "HF Benchmark Tracker",
};

const CATEGORY_COLORS: Record<string, string> = {
  Models: "bg-blue-100 text-blue-800",
  APIs: "bg-green-100 text-green-800",
  Pricing: "bg-purple-100 text-purple-800",
  Benchmarks: "bg-yellow-100 text-yellow-800",
  Safety: "bg-red-100 text-red-800",
  Research: "bg-sky-100 text-sky-800",
  Tooling: "bg-gray-100 text-gray-800",
  Other: "bg-gray-100 text-gray-700",
};

function duration(start: string, end: string | null): string {
  if (!end) return "In progress...";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  const mins = Math.floor(ms / 60000);
  const secs = Math.floor((ms % 60000) / 1000);
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

export default function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const runId = parseInt(id);

  const { data: run } = useSWR<Run>(
    `run-${runId}`,
    () => getRun(runId),
    { refreshInterval: (data) => data?.status === "running" ? 4000 : 0 }
  );

  const { data: findings } = useSWR<Finding[]>(
    `run-findings-${runId}`,
    () => getRunFindings(runId),
    { refreshInterval: run?.status === "running" ? 4000 : 0 }
  );

  if (!run) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400">
        Loading run details...
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link href="/runs" className="text-sm text-[#1e3a5f] hover:underline">
              ← Runs
            </Link>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Run #{run.id}</h1>
          <p className="text-sm text-gray-500 mt-1">
            Started: {new Date(run.started_at).toLocaleString()} ·
            Duration: {duration(run.started_at, run.finished_at)} ·
            Triggered by: {run.triggered_by}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-sm px-3 py-1 rounded-full font-medium border ${STATUS_STYLES[run.status] || ""}`}>
            {run.status === "running" && (
              <span className="inline-block w-2 h-2 bg-blue-500 rounded-full mr-1.5 animate-pulse" />
            )}
            {run.status}
          </span>
          {run.digest?.id && (
            <a
              href={downloadDigestUrl(run.digest.id)}
              target="_blank"
              className="px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#2a4f7c] transition"
            >
              Download PDF
            </a>
          )}
        </div>
      </div>

      {/* Agent status grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {Object.entries(AGENT_LABELS).map(([key, label]) => {
          const status = run.agent_statuses?.[key];
          return (
            <div
              key={key}
              className={`bg-white rounded-xl border p-4 ${
                status === "completed"
                  ? "border-green-200"
                  : status === "failed"
                  ? "border-red-200"
                  : status === "running"
                  ? "border-blue-200"
                  : "border-gray-200"
              }`}
            >
              <p className="text-xs font-medium text-gray-500 mb-1">{label}</p>
              <p className={`text-sm font-semibold ${
                status === "completed" ? "text-green-700" :
                status === "failed" ? "text-red-700" :
                status === "running" ? "text-blue-700" :
                "text-gray-400"
              }`}>
                {status || (run.status === "running" ? "pending..." : "—")}
              </p>
              <p className="text-xs text-gray-400 mt-1">
                {(findings || []).filter((f) => f.agent_type === key).length} findings
              </p>
            </div>
          );
        })}
      </div>

      {/* Per-agent logs */}
      {run.agent_logs && Object.keys(run.agent_logs).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 mb-6">
          <div className="px-5 py-3 border-b border-gray-100">
            <h2 className="font-semibold text-gray-800 text-sm">Agent Logs</h2>
          </div>
          <div className="divide-y divide-gray-100">
            {Object.entries(run.agent_logs).map(([agentType, logs]) => (
              <div key={agentType} className="px-5 py-3">
                <p className="text-xs font-semibold text-gray-500 mb-1.5">
                  {AGENT_LABELS[agentType] || agentType}
                </p>
                <div className="space-y-0.5">
                  {(logs as AgentLogEntry[]).map((entry, i) => (
                    <p key={i} className={`text-xs font-mono ${
                      entry.status === "error" ? "text-red-600" :
                      entry.status === "success" ? "text-green-700" :
                      "text-gray-500"
                    }`}>
                      {entry.status === "error" ? "✗" : entry.status === "success" ? "✓" : "·"} {entry.msg}
                    </p>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Findings list */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800">
            Findings ({findings?.length ?? 0})
          </h2>
          {run.status === "running" && (
            <span className="text-xs text-blue-600 animate-pulse">Updating...</span>
          )}
        </div>
        <div className="divide-y divide-gray-100">
          {findings?.length === 0 && (
            <p className="text-sm text-gray-400 text-center py-8">
              {run.status === "running" ? "Findings will appear here as agents complete..." : "No findings for this run."}
            </p>
          )}
          {findings?.map((f: Finding) => (
            <div key={f.id} className="px-5 py-4 hover:bg-gray-50">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    {f.category && (
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLORS[f.category] || "bg-gray-100"}`}>
                        {f.category}
                      </span>
                    )}
                    <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded-full">
                      {AGENT_LABELS[f.agent_type] || f.agent_type}
                    </span>
                    {f.publisher && (
                      <span className="text-xs text-gray-500 font-medium">{f.publisher}</span>
                    )}
                  </div>
                  <p className="font-medium text-gray-800">{f.title}</p>
                  {f.summary_short && (
                    <p className="text-sm text-gray-500 mt-1">{f.summary_short}</p>
                  )}
                  {f.why_it_matters && (
                    <p className="text-xs text-green-700 mt-1.5 bg-green-50 px-2 py-1 rounded">
                      {f.why_it_matters}
                    </p>
                  )}
                </div>
                <div className="flex-shrink-0 text-right">
                  <p className="text-xs text-gray-400">{(f.impact_score * 100).toFixed(0)}% impact</p>
                  <a
                    href={f.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-[#1e3a5f] hover:underline mt-1 block"
                  >
                    Source →
                  </a>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
