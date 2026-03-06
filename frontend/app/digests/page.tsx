"use client";
import useSWR from "swr";
import { getDigests, downloadDigestUrl } from "@/lib/api";
import type { Digest } from "@/lib/api";

export default function DigestsPage() {
  const { data } = useSWR("digests", () => getDigests());

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Digest Archive</h1>
          <p className="text-sm text-gray-500 mt-1">{data?.total ?? 0} digests</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data?.digests?.length === 0 && (
          <div className="col-span-3 bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
            No digests yet. Trigger a run to generate the first digest.
          </div>
        )}
        {data?.digests?.map((d: Digest) => (
          <div
            key={d.id}
            className="bg-white rounded-xl border border-gray-200 hover:border-gray-300 transition p-5 flex flex-col"
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <p className="font-semibold text-gray-800">
                  {new Date(d.created_at).toLocaleDateString("en-US", {
                    weekday: "short",
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                  })}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Run #{d.run_id} · {new Date(d.created_at).toLocaleTimeString()}
                </p>
              </div>
              <div className="flex flex-col items-end gap-1">
                {d.email_sent ? (
                  <span className="text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full">
                    Email sent
                  </span>
                ) : (
                  <span className="text-xs bg-gray-50 text-gray-500 border border-gray-200 px-2 py-0.5 rounded-full">
                    No email
                  </span>
                )}
              </div>
            </div>

            {d.html_summary && (
              <p className="text-sm text-gray-600 flex-1 line-clamp-4 mb-4">
                {d.html_summary.replace(/^- /gm, "• ")}
              </p>
            )}

            <div className="mt-auto pt-3 border-t border-gray-100">
              {d.has_pdf ? (
                <a
                  href={downloadDigestUrl(d.id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block w-full text-center px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#2a4f7c] transition"
                >
                  Download PDF
                </a>
              ) : (
                <p className="text-center text-xs text-gray-400">PDF not available</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
