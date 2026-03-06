"use client";
import useSWR from "swr";
import { useState } from "react";
import { getFindings, getFindingDiff } from "@/lib/api";
import type { Finding } from "@/lib/api";

const CATEGORIES = ["Models", "APIs", "Pricing", "Benchmarks", "Safety", "Research", "Tooling", "Other"];
const AGENT_TYPES = ["competitor", "model_provider", "research", "hf_benchmark"];
const AGENT_LABELS: Record<string, string> = {
  competitor: "Competitor",
  model_provider: "Model Provider",
  research: "Research",
  hf_benchmark: "HF Benchmark",
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

function ConfidenceBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full bg-green-500"
          style={{ width: `${(value * 100).toFixed(0)}%` }}
        />
      </div>
      <span className="text-xs text-gray-400">{(value * 100).toFixed(0)}%</span>
    </div>
  );
}

function DiffViewer({ findingId }: { findingId: number }) {
  const { data, isLoading } = useSWR(
    `diff-${findingId}`,
    () => getFindingDiff(findingId)
  );

  if (isLoading) return <p className="text-xs text-gray-400 mt-2">Loading diff...</p>;
  if (!data?.has_diff) {
    return (
      <p className="text-xs text-gray-400 mt-2 italic">
        {data?.message || "No diff available (first snapshot)"}
      </p>
    );
  }

  return (
    <div className="mt-3">
      <p className="text-xs font-semibold text-gray-600 mb-1">
        What Changed <span className="font-normal text-gray-400">({data.prev_date?.slice(0, 10)} → {data.curr_date?.slice(0, 10)})</span>
      </p>
      <div className="bg-gray-900 rounded-lg p-3 overflow-x-auto max-h-64 overflow-y-auto">
        {data.diff?.map((line, i) => (
          <div key={i} className={`text-xs font-mono whitespace-pre ${
            line.startsWith("+") && !line.startsWith("+++") ? "text-green-400" :
            line.startsWith("-") && !line.startsWith("---") ? "text-red-400" :
            line.startsWith("@@") ? "text-blue-300" :
            "text-gray-400"
          }`}>{line}</div>
        ))}
      </div>
    </div>
  );
}

export default function FindingsPage() {
  const [agentFilter, setAgentFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [showDiff, setShowDiff] = useState<number | null>(null);

  const params: Record<string, string> = { limit: "50" };
  if (agentFilter) params.agent_type = agentFilter;
  if (categoryFilter) params.category = categoryFilter;

  const { data } = useSWR(
    ["findings", agentFilter, categoryFilter],
    () => getFindings(params),
    { refreshInterval: 15000 }
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Findings Explorer</h1>
          <p className="text-sm text-gray-500 mt-1">{data?.total ?? 0} total findings</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-4 mb-5">
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setAgentFilter("")}
            className={`px-3 py-1 rounded-full text-xs font-medium transition border ${
              !agentFilter ? "bg-[#1e3a5f] text-white border-[#1e3a5f]" : "bg-white border-gray-200 text-gray-600"
            }`}
          >
            All Agents
          </button>
          {AGENT_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setAgentFilter(t)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition border ${
                agentFilter === t ? "bg-[#1e3a5f] text-white border-[#1e3a5f]" : "bg-white border-gray-200 text-gray-600"
              }`}
            >
              {AGENT_LABELS[t]}
            </button>
          ))}
        </div>
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setCategoryFilter("")}
            className={`px-3 py-1 rounded-full text-xs font-medium transition border ${
              !categoryFilter ? "bg-[#0f5132] text-white border-[#0f5132]" : "bg-white border-gray-200 text-gray-600"
            }`}
          >
            All Categories
          </button>
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCategoryFilter(c)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition border ${
                categoryFilter === c ? "bg-[#0f5132] text-white border-[#0f5132]" : "bg-white border-gray-200 text-gray-600"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* Findings list */}
      <div className="space-y-3">
        {data?.findings?.length === 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
            No findings match the current filters.
          </div>
        )}
        {data?.findings?.map((f: Finding) => (
          <div
            key={f.id}
            className="bg-white rounded-xl border border-gray-200 hover:border-gray-300 transition overflow-hidden"
          >
            <button
              className="w-full text-left p-5"
              onClick={() => setExpanded(expanded === f.id ? null : f.id)}
            >
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
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
                  <h3 className="font-semibold text-gray-800">{f.title}</h3>
                  {f.summary_short && (
                    <p className="text-sm text-gray-500 mt-1">{f.summary_short}</p>
                  )}
                </div>
                <div className="flex-shrink-0 text-right min-w-[80px]">
                  <p className="text-xs text-gray-400 mb-1">{new Date(f.date_detected).toLocaleDateString()}</p>
                  <div className="w-20">
                    <ConfidenceBar value={f.confidence} />
                  </div>
                </div>
              </div>
            </button>

            {/* Expanded detail */}
            {expanded === f.id && (
              <div className="border-t border-gray-100 px-5 pb-5 pt-4 bg-gray-50">
                {f.why_it_matters && (
                  <div className="mb-3 p-3 bg-green-50 border-l-4 border-green-500 rounded-r-lg">
                    <p className="text-xs font-semibold text-green-800 mb-1">Why it matters</p>
                    <p className="text-sm text-green-700">{f.why_it_matters}</p>
                  </div>
                )}
                {f.summary_long && (
                  <div className="mb-3">
                    <p className="text-xs font-semibold text-gray-600 mb-1">Details</p>
                    <p className="text-sm text-gray-600 whitespace-pre-wrap">{f.summary_long}</p>
                  </div>
                )}
                {f.tags?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-3">
                    {f.tags.map((tag) => (
                      <span key={tag} className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded-full">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-3 mt-2">
                  <a
                    href={f.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-[#1e3a5f] hover:underline"
                  >
                    View source →
                  </a>
                  <button
                    onClick={() => setShowDiff(showDiff === f.id ? null : f.id)}
                    className="text-xs text-gray-500 hover:text-gray-700 underline"
                  >
                    {showDiff === f.id ? "Hide diff" : "What changed?"}
                  </button>
                </div>
                {showDiff === f.id && <DiffViewer findingId={f.id} />}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
