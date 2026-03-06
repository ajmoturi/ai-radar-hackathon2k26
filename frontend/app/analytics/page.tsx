"use client";
import useSWR from "swr";
import { getFindings, getFindingsStats, getEntityHeatmap } from "@/lib/api";
import type { Finding, FindingsStats } from "@/lib/api";

const CATEGORY_COLORS: Record<string, string> = {
  Models: "bg-blue-500",
  APIs: "bg-green-500",
  Pricing: "bg-purple-500",
  Benchmarks: "bg-yellow-500",
  Safety: "bg-red-500",
  Research: "bg-sky-500",
  Tooling: "bg-gray-500",
  Other: "bg-gray-400",
};

const CATEGORY_TEXT: Record<string, string> = {
  Models: "text-blue-700",
  APIs: "text-green-700",
  Pricing: "text-purple-700",
  Benchmarks: "text-yellow-700",
  Safety: "text-red-700",
  Research: "text-sky-700",
  Tooling: "text-gray-700",
  Other: "text-gray-600",
};

function SOTAWatchSection() {
  const { data } = useSWR("sota-findings", () =>
    getFindings({ agent_type: "hf_benchmark", limit: "20" })
  );
  const { data: modelData } = useSWR("model-findings", () =>
    getFindings({ agent_type: "model_provider", limit: "20" })
  );

  const benchmarkFindings = [
    ...(data?.findings || []),
    ...(modelData?.findings || []).filter((f: Finding) => f.category === "Benchmarks"),
  ].sort((a, b) => b.impact_score - a.impact_score).slice(0, 12);

  if (benchmarkFindings.length === 0) {
    return (
      <p className="text-sm text-gray-400 text-center py-8">
        No benchmark findings yet. Trigger a run to populate data.
      </p>
    );
  }

  const maxScore = Math.max(...benchmarkFindings.map((f) => f.impact_score), 0.01);

  return (
    <div className="space-y-2">
      {benchmarkFindings.map((f: Finding) => (
        <div key={f.id} className="flex items-center gap-3 group">
          <div className="w-36 text-xs text-gray-600 truncate flex-shrink-0 text-right" title={f.publisher || f.agent_type}>
            {f.publisher || f.agent_type}
          </div>
          <div className="flex-1 relative h-7 bg-gray-100 rounded overflow-hidden">
            <div
              className={`h-full rounded transition-all ${CATEGORY_COLORS[f.category || "Other"] || "bg-gray-400"} opacity-80`}
              style={{ width: `${(f.impact_score / maxScore) * 100}%` }}
            />
            <span className="absolute inset-0 flex items-center px-2 text-xs font-medium text-gray-800 truncate">
              {f.title}
            </span>
          </div>
          <div className="w-10 text-xs text-gray-500 text-right flex-shrink-0">
            {(f.impact_score * 100).toFixed(0)}%
          </div>
        </div>
      ))}
      <div className="pt-2 flex flex-wrap gap-3">
        {Object.entries(CATEGORY_COLORS).map(([cat, cls]) => (
          <div key={cat} className="flex items-center gap-1.5">
            <div className={`w-3 h-3 rounded-sm ${cls}`} />
            <span className="text-xs text-gray-500">{cat}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function EntityHeatmapSection() {
  const { data, isLoading } = useSWR("entity-heatmap", getEntityHeatmap);

  if (isLoading) {
    return <p className="text-sm text-gray-400 text-center py-8">Loading heatmap...</p>;
  }
  if (!data || data.entities.length === 0) {
    return (
      <p className="text-sm text-gray-400 text-center py-8">
        No entity data yet. Trigger a run to populate data.
      </p>
    );
  }

  const { entities, categories } = data;
  const maxCount = Math.max(...entities.flatMap((e) => Object.values(e.counts)), 1);

  function heatColor(count: number): string {
    if (count === 0) return "bg-gray-50 text-gray-300";
    const pct = count / maxCount;
    if (pct >= 0.8) return "bg-[#1e3a5f] text-white";
    if (pct >= 0.5) return "bg-blue-400 text-white";
    if (pct >= 0.25) return "bg-blue-200 text-blue-900";
    return "bg-blue-50 text-blue-700";
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-separate border-spacing-0.5">
        <thead>
          <tr>
            <th className="text-left font-medium text-gray-500 px-2 py-1 sticky left-0 bg-white">Entity</th>
            {categories.map((cat) => (
              <th key={cat} className={`font-medium px-1 py-1 text-center whitespace-nowrap ${CATEGORY_TEXT[cat] || "text-gray-600"}`}>
                {cat}
              </th>
            ))}
            <th className="font-medium text-gray-500 px-2 py-1 text-center">Total</th>
          </tr>
        </thead>
        <tbody>
          {entities.map((row) => {
            const total = Object.values(row.counts).reduce((a, b) => a + b, 0);
            return (
              <tr key={row.entity}>
                <td className="px-2 py-1 font-medium text-gray-700 sticky left-0 bg-white max-w-[120px] truncate" title={row.entity}>
                  {row.entity}
                </td>
                {categories.map((cat) => {
                  const count = row.counts[cat] || 0;
                  return (
                    <td key={cat} className={`px-2 py-1 text-center rounded font-semibold ${heatColor(count)}`}>
                      {count > 0 ? count : ""}
                    </td>
                  );
                })}
                <td className="px-2 py-1 text-center text-gray-500 font-medium">{total}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-xs text-gray-400 mt-3">
        Darker cells = more findings. Showing top 15 entities by total finding count.
      </p>
    </div>
  );
}

function CategoryBreakdown() {
  const { data } = useSWR<FindingsStats>("findings-stats", getFindingsStats);

  if (!data || data.total === 0) {
    return <p className="text-sm text-gray-400 text-center py-4">No data yet.</p>;
  }

  const sorted = Object.entries(data.by_category)
    .filter(([, v]) => v > 0)
    .sort(([, a], [, b]) => b - a);
  const max = sorted[0]?.[1] || 1;

  return (
    <div className="space-y-2">
      {sorted.map(([cat, count]) => (
        <div key={cat} className="flex items-center gap-3">
          <div className="w-20 text-xs text-right text-gray-600 flex-shrink-0">{cat}</div>
          <div className="flex-1 h-5 bg-gray-100 rounded overflow-hidden">
            <div
              className={`h-full rounded ${CATEGORY_COLORS[cat] || "bg-gray-400"} opacity-80`}
              style={{ width: `${(count / max) * 100}%` }}
            />
          </div>
          <div className="w-8 text-xs text-gray-500 text-right">{count}</div>
        </div>
      ))}
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
        <p className="text-sm text-gray-500 mt-1">Visualizations of findings across providers, topics, and benchmarks</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <div className="lg:col-span-1 bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-800 mb-4">Findings by Category</h2>
          <CategoryBreakdown />
        </div>
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-800 mb-1">SOTA Watch Leaderboard</h2>
          <p className="text-xs text-gray-400 mb-4">Benchmark and model provider findings ranked by impact score</p>
          <SOTAWatchSection />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="font-semibold text-gray-800 mb-1">Entity Heatmap</h2>
        <p className="text-xs text-gray-400 mb-4">Providers and models vs finding categories — darker = more findings</p>
        <EntityHeatmapSection />
      </div>
    </div>
  );
}
