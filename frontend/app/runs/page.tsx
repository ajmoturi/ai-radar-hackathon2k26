"use client";
import useSWR from "swr";
import Link from "next/link";
import { getRuns, triggerRun, downloadDigestUrl } from "@/lib/api";
import type { Run } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-green-50 text-green-700 border-green-200",
  running: "bg-blue-50 text-blue-700 border-blue-200",
  partial: "bg-yellow-50 text-yellow-700 border-yellow-200",
  failed: "bg-red-50 text-red-700 border-red-200",
};

const AGENT_LABELS: Record<string, string> = {
  competitor: "Competitor",
  model_provider: "Model Provider",
  research: "Research",
  hf_benchmark: "HF Benchmark",
};

function duration(start: string, end: string | null): string {
  if (!end) return "In progress...";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  const mins = Math.floor(ms / 60000);
  const secs = Math.floor((ms % 60000) / 1000);
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

export default function RunsPage() {
  const { data, mutate } = useSWR("runs", () => getRuns({ limit: 50 }), {
    refreshInterval: 5000,
  });

  const handleTrigger = async () => {
    await triggerRun();
    setTimeout(() => mutate(), 3000);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Runs</h1>
          <p className="text-sm text-gray-500 mt-1">{data?.total ?? 0} total runs</p>
        </div>
        <button
          onClick={handleTrigger}
          className="px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#2a4f7c]"
        >
          Trigger Run
        </button>
      </div>

      <div className="space-y-3">
        {data?.runs?.length === 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
            No runs yet. Click "Trigger Run" to start.
          </div>
        )}
        {data?.runs?.map((run: Run) => (
          <div
            key={run.id}
            className={`bg-white rounded-xl border p-5 ${STATUS_STYLES[run.status] || "border-gray-200"}`}
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3 mb-1">
                  <span className="font-semibold text-gray-800">Run #{run.id}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${STATUS_STYLES[run.status]}`}>
                    {run.status}
                  </span>
                  <span className="text-xs text-gray-400">
                    via {run.triggered_by}
                  </span>
                </div>
                <p className="text-sm text-gray-500">
                  Started: {new Date(run.started_at).toLocaleString()} ·{" "}
                  Duration: {duration(run.started_at, run.finished_at)}
                </p>
              </div>
              <div className="flex gap-2 items-center">
                {run.finding_count > 0 && (
                  <span className="text-sm text-gray-500">{run.finding_count} findings</span>
                )}
                {run.digest?.id && (
                  <a
                    href={downloadDigestUrl(run.digest.id)}
                    target="_blank"
                    className="px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
                  >
                    PDF
                  </a>
                )}
              </div>
            </div>

            {/* Agent status grid */}
            {Object.keys(run.agent_statuses).length > 0 && (
              <div className="mt-3 flex gap-2 flex-wrap">
                {Object.entries(run.agent_statuses).map(([agent, status]) => (
                  <div
                    key={agent}
                    className={`text-xs px-2 py-1 rounded-md border ${
                      status === "completed"
                        ? "bg-green-50 border-green-200 text-green-700"
                        : "bg-red-50 border-red-200 text-red-700"
                    }`}
                  >
                    {AGENT_LABELS[agent] || agent}: {status}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
