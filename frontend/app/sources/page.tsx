"use client";
import useSWR from "swr";
import React, { useState } from "react";
import {
  getSources, createSource, updateSource, deleteSource, seedDefaultSources,
} from "@/lib/api";
import type { Source } from "@/lib/api";

const AGENT_TYPES = ["competitor", "model_provider", "research", "hf_benchmark"];
const AGENT_LABELS: Record<string, string> = {
  competitor: "Competitor",
  model_provider: "Model Provider",
  research: "Research",
  hf_benchmark: "HF Benchmark",
};

function SourceForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: Partial<Source>;
  onSave: (data: Partial<Source>) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<Partial<Source>>({
    name: initial?.name || "",
    agent_type: initial?.agent_type || "competitor",
    urls: initial?.urls || [],
    rss_feeds: initial?.rss_feeds || [],
    keywords: initial?.keywords || [],
    rate_limit: initial?.rate_limit || 1.0,
    enabled: initial?.enabled !== false,
  });
  const [urlInput, setUrlInput] = useState(form.urls?.join("\n") || "");
  const [rssInput, setRssInput] = useState(form.rss_feeds?.join("\n") || "");
  const [keyInput, setKeyInput] = useState(form.keywords?.join(", ") || "");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      ...form,
      urls: urlInput.split("\n").map((u) => u.trim()).filter(Boolean),
      rss_feeds: rssInput.split("\n").map((u) => u.trim()).filter(Boolean),
      keywords: keyInput.split(",").map((k) => k.trim()).filter(Boolean),
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-medium text-gray-700">Name</label>
          <input
            className="mt-1 block w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700">Agent Type</label>
          <select
            className="mt-1 block w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            value={form.agent_type}
            onChange={(e) => setForm({ ...form, agent_type: e.target.value })}
          >
            {AGENT_TYPES.map((t) => (
              <option key={t} value={t}>{AGENT_LABELS[t]}</option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className="text-sm font-medium text-gray-700">URLs (one per line)</label>
        <textarea
          className="mt-1 block w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
          rows={3}
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
        />
      </div>
      <div>
        <label className="text-sm font-medium text-gray-700">RSS Feeds (one per line)</label>
        <textarea
          className="mt-1 block w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
          rows={2}
          value={rssInput}
          onChange={(e) => setRssInput(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-medium text-gray-700">Keywords (comma-separated)</label>
          <input
            className="mt-1 block w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
          />
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700">Rate Limit (req/sec)</label>
          <input
            type="number"
            step="0.1"
            min="0.1"
            max="10"
            className="mt-1 block w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            value={form.rate_limit}
            onChange={(e) => setForm({ ...form, rate_limit: parseFloat(e.target.value) })}
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="enabled"
          checked={form.enabled}
          onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
        />
        <label htmlFor="enabled" className="text-sm text-gray-700">Enabled</label>
      </div>
      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          className="px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#2a4f7c]"
        >
          Save
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 bg-white border border-gray-300 rounded-lg text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function SourcesPage() {
  const { data: sources, mutate } = useSWR<Source[]>("sources", () => getSources());
  const [filter, setFilter] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Source | null>(null);

  const filtered = (sources || []).filter(
    (s) => !filter || s.agent_type === filter
  );

  const handleCreate = async (data: Partial<Source>) => {
    await createSource(data);
    mutate();
    setShowAdd(false);
  };

  const handleUpdate = async (id: number, data: Partial<Source>) => {
    await updateSource(id, data);
    mutate();
    setEditing(null);
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this source?")) return;
    await deleteSource(id);
    mutate();
  };

  const handleSeed = async () => {
    const result = await seedDefaultSources() as { seeded: number };
    mutate();
    alert(`Seeded ${result.seeded} default sources.`);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Sources</h1>
        <div className="flex gap-3">
          <button
            onClick={handleSeed}
            className="px-4 py-2 bg-white border border-gray-300 rounded-lg text-sm hover:bg-gray-50"
          >
            Seed Defaults
          </button>
          <button
            onClick={() => setShowAdd(true)}
            className="px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium"
          >
            Add Source
          </button>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-5">
        {["", ...AGENT_TYPES].map((type) => (
          <button
            key={type}
            onClick={() => setFilter(type)}
            className={`px-3 py-1.5 rounded-full text-sm font-medium transition ${
              filter === type
                ? "bg-[#1e3a5f] text-white"
                : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
            }`}
          >
            {type ? AGENT_LABELS[type] : "All"}
          </button>
        ))}
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 mb-5">
          <h2 className="font-semibold text-gray-800 mb-4">New Source</h2>
          <SourceForm
            onSave={handleCreate}
            onCancel={() => setShowAdd(false)}
          />
        </div>
      )}

      {/* Source table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Name</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Type</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">URLs</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Last Updated</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="text-center py-8 text-gray-400">
                  No sources. Click "Seed Defaults" to add pre-configured sources.
                </td>
              </tr>
            )}
            {filtered.map((s) => (
              <React.Fragment key={s.id}>
                <tr className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">{s.name}</td>
                  <td className="px-4 py-3 text-gray-500">{AGENT_LABELS[s.agent_type]}</td>
                  <td className="px-4 py-3 text-gray-500">
                    {s.urls.length} URL{s.urls.length !== 1 ? "s" : ""}
                    {s.rss_feeds.length > 0 && `, ${s.rss_feeds.length} RSS`}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      s.enabled ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {s.enabled ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {s.updated_at
                      ? new Date(s.updated_at).toLocaleDateString()
                      : new Date(s.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setEditing(editing?.id === s.id ? null : s)}
                      className="text-[#1e3a5f] hover:underline text-xs mr-3"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(s.id)}
                      className="text-red-500 hover:underline text-xs"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
                {editing?.id === s.id && (
                  <tr>
                    <td colSpan={6} className="px-4 py-4 bg-gray-50">
                      <SourceForm
                        initial={s}
                        onSave={(data) => handleUpdate(s.id, data)}
                        onCancel={() => setEditing(null)}
                      />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
