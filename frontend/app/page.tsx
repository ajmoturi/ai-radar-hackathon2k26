"use client";
import useSWR from "swr";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { getStats, getFindings, getRuns, triggerRun, downloadDigestUrl, getAnthropicHealth } from "@/lib/api";
import type { Stats, Finding, Run } from "@/lib/api";

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

const STATUS_COLORS: Record<string, string> = {
  completed: "text-green-700 bg-green-50",
  running: "text-blue-700 bg-blue-50",
  partial: "text-yellow-700 bg-yellow-50",
  failed: "text-red-700 bg-red-50",
};

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold text-[#1e3a5f] mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [triggering, setTriggering] = useState(false);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const { data: stats, mutate: mutateStats } = useSWR<Stats>("stats", getStats, { refreshInterval: 10000 });
  const { data: anthropicHealth } = useSWR("anthropic-health", getAnthropicHealth, { refreshInterval: 60000 });
  const { data: findingsData } = useSWR("top-findings", () =>
    getFindings({ limit: 10, offset: 0 })
  );
  const { data: runsData, mutate: mutateRuns } = useSWR("recent-runs", () => getRuns({ limit: 5 }), { refreshInterval: 5000 });

  const handleTrigger = async () => {
    setTriggering(true);
    setTriggerMsg(null);
    try {
      const result = await triggerRun() as { run_id: number };
      setTriggerMsg(`Run #${result.run_id} started — pipeline is running`);
      mutateStats();
      mutateRuns();
      // Navigate to runs page after short delay
      setTimeout(() => router.push("/runs"), 1500);
    } catch (e) {
      setTriggerMsg("Failed to trigger run. Is the backend running?");
    } finally {
      setTriggering(false);
    }
  };

  const lastRun = stats?.last_run;
  const lastDigest = stats?.last_digest;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">
            {lastRun
              ? `Last run: ${new Date(lastRun.started_at).toLocaleString()} — ${lastRun.status}`
              : "No runs yet"}
          </p>
        </div>
        <div className="flex gap-3">
          {lastDigest?.id && (
            <a
              href={downloadDigestUrl(lastDigest.id)}
              target="_blank"
              className="px-4 py-2 bg-white border border-gray-300 rounded-lg text-sm font-medium hover:bg-gray-50 transition"
            >
              Download Latest PDF
            </a>
          )}
          <button
            onClick={handleTrigger}
            disabled={triggering}
            className="px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#2a4f7c] transition disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {triggering ? "Starting..." : "Run Now"}
          </button>
        </div>
      </div>

      {/* LLM provider warning */}
      {anthropicHealth && !anthropicHealth.ok && (
        <div className="mb-4 px-4 py-3 rounded-lg text-sm font-medium bg-amber-50 text-amber-800 border border-amber-200 flex items-start gap-2">
          <span className="text-amber-500 mt-0.5">⚠</span>
          <div>
            <span className="font-semibold">
              {anthropicHealth.provider === "azure_openai" ? "Azure OpenAI" : "Anthropic"} issue:{" "}
            </span>
            {anthropicHealth.error}
            <span className="ml-2 text-amber-600 text-xs">(set LLM_PROVIDER in .env to switch)</span>
          </div>
        </div>
      )}

      {/* Trigger feedback */}
      {triggerMsg && (
        <div className={`mb-4 px-4 py-3 rounded-lg text-sm font-medium ${
          triggerMsg.startsWith("Failed")
            ? "bg-red-50 text-red-700 border border-red-200"
            : "bg-blue-50 text-blue-700 border border-blue-200"
        }`}>
          {triggerMsg}
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Runs" value={stats?.total_runs ?? "—"} />
        <StatCard label="Total Findings" value={stats?.total_findings ?? "—"} />
        <StatCard label="Today's Findings" value={stats?.today_findings ?? "—"} />
        <StatCard
          label="Last Run Status"
          value={lastRun?.status ?? "—"}
          sub={lastRun?.finished_at ? `Finished ${new Date(lastRun.finished_at).toLocaleTimeString()}` : undefined}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Top findings */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-800">Top Findings Today</h2>
              <Link href="/findings" className="text-sm text-[#1e3a5f] hover:underline">View all</Link>
            </div>
            <div className="space-y-3">
              {findingsData?.findings?.length === 0 && (
                <p className="text-sm text-gray-400 py-4 text-center">No findings yet. Trigger a run to get started.</p>
              )}
              {findingsData?.findings?.map((f: Finding) => (
                <div key={f.id} className="flex gap-3 p-3 rounded-lg hover:bg-gray-50 border border-gray-100">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      {f.category && (
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLORS[f.category] || "bg-gray-100 text-gray-700"}`}>
                          {f.category}
                        </span>
                      )}
                      <span className="text-xs text-gray-400">{f.publisher}</span>
                    </div>
                    <p className="text-sm font-medium text-gray-800 truncate">{f.title}</p>
                    {f.summary_short && (
                      <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{f.summary_short}</p>
                    )}
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="text-xs text-gray-400">{(f.impact_score * 100).toFixed(0)}%</p>
                    <p className="text-xs text-gray-300">impact</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Recent runs */}
        <div>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-800">Recent Runs</h2>
              <Link href="/runs" className="text-sm text-[#1e3a5f] hover:underline">View all</Link>
            </div>
            <div className="space-y-2">
              {runsData?.runs?.length === 0 && (
                <p className="text-sm text-gray-400 text-center py-4">No runs yet.</p>
              )}
              {runsData?.runs?.map((run: Run) => (
                <Link
                  key={run.id}
                  href={`/runs/${run.id}`}
                  className="flex items-center justify-between p-2 rounded-lg hover:bg-gray-50 border border-gray-100"
                >
                  <div>
                    <p className="text-sm font-medium text-gray-700">Run #{run.id}</p>
                    <p className="text-xs text-gray-400">
                      {new Date(run.started_at).toLocaleString()}
                    </p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[run.status] || ""}`}>
                    {run.status}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
