"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Nav from "@/components/Nav";
import { apiGet } from "@/lib/api";
import { getUser } from "@/lib/auth";

type QualityRow = {
  id: number;
  job_id: string;
  filename: string | null;
  original_chunks: number;
  checked_chunks: number;
  kept_chunks: number;
  rejected_chunks: number;
  duplicate_chunks: number;
  quality_passed: boolean;
  issues: Record<string, number>;
  sample_issues: Array<{
    page?: number;
    source?: string;
    issues: string[];
    preview: string;
  }>;
  created_at: string | null;
};

type QualityListResp = {
  items: QualityRow[];
  limit: number;
  offset: number;
  only_failed: boolean;
};

const PAGE_SIZE = 50;

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function shortJobId(jobId: string): string {
  return jobId.length > 12 ? `${jobId.slice(0, 8)}…${jobId.slice(-4)}` : jobId;
}

export default function AdminIngestionQualityPage() {
  const router = useRouter();
  const [rows, setRows] = useState<QualityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    const u = getUser();
    if (!u) router.replace("/login");
    else if (u.role !== "admin") router.replace("/chat");
  }, [router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
        only_failed: String(onlyFailed),
      });
      const resp = await apiGet<QualityListResp>(`/admin/ingestion-quality?${params}`);
      setRows(resp.items);
      setHasMore(resp.items.length === PAGE_SIZE);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "failed to load");
    } finally {
      setLoading(false);
    }
  }, [offset, onlyFailed]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-6 space-y-4">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold">Ingestion Quality</h1>
          <label className="flex items-center gap-2 text-sm text-slate-600 ml-auto">
            <input
              type="checkbox"
              checked={onlyFailed}
              onChange={(e) => {
                setOffset(0);
                setOnlyFailed(e.target.checked);
              }}
            />
            Only failed
          </label>
          <button
            onClick={load}
            disabled={loading}
            className="text-sm border rounded px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded p-3">
            {error}
          </div>
        )}

        <div className="bg-white border rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Time</th>
                <th className="text-left px-3 py-2 font-medium">File</th>
                <th className="text-left px-3 py-2 font-medium">Job ID</th>
                <th className="text-right px-3 py-2 font-medium">Original</th>
                <th className="text-right px-3 py-2 font-medium">Kept</th>
                <th className="text-right px-3 py-2 font-medium">Rejected</th>
                <th className="text-right px-3 py-2 font-medium">Duplicates</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center text-slate-500 px-3 py-8">
                    No ingestion quality records found.
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.id} className="border-t">
                  <td className="px-3 py-2 whitespace-nowrap text-slate-600">
                    {formatTime(row.created_at)}
                  </td>
                  <td className="px-3 py-2">{row.filename || "—"}</td>
                  <td className="px-3 py-2">
                    <code className="text-xs text-slate-600" title={row.job_id}>
                      {shortJobId(row.job_id)}
                    </code>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.original_chunks}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.kept_chunks}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.rejected_chunks}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.duplicate_chunks}</td>
                  <td className="px-3 py-2">
                    {row.quality_passed ? (
                      <span className="inline-block text-xs font-medium px-2 py-0.5 rounded bg-green-100 text-green-700">
                        Passed
                      </span>
                    ) : (
                      <span className="inline-block text-xs font-medium px-2 py-0.5 rounded bg-red-100 text-red-700">
                        Failed
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between text-sm text-slate-600">
          <span>
            Showing {rows.length === 0 ? 0 : offset + 1}–{offset + rows.length}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0 || loading}
              className="border rounded px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={!hasMore || loading}
              className="border rounded px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
