"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Nav from "@/components/Nav";
import { apiGet, apiPostForm } from "@/lib/api";
import { getUser } from "@/lib/auth";

type IngestResp = { job_id: string; stream_id: string; status: string };
type StatusResp = Record<string, string> & { job_id: string; status?: string };

export default function AdminIngestPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<IngestResp | null>(null);
  const [status, setStatus] = useState<StatusResp | null>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) router.replace("/login");
    else if (u.role !== "admin") router.replace("/chat");
  }, [router]);

  useEffect(() => {
    if (!job) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await apiGet<StatusResp>(`/ingest/status/${job.job_id}`);
        if (stop) return;
        setStatus(s);
        if (s.status === "done" || s.status === "failed" || s.status === "dead") return;
        setTimeout(tick, 2000);
      } catch {
        if (!stop) setTimeout(tick, 5000);
      }
    };
    tick();
    return () => { stop = true; };
  }, [job]);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setError(null);
    setStatus(null);
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const resp = await apiPostForm<IngestResp>("/ingest", fd);
      setJob(resp);
      setFile(null);
      (document.getElementById("pdf-file") as HTMLInputElement | null)?.value && (
        (document.getElementById("pdf-file") as HTMLInputElement).value = ""
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-6 space-y-6">
        <h1 className="text-xl font-semibold">Ingest PDF</h1>

        <form onSubmit={upload} className="bg-white border rounded-lg p-4 space-y-3">
          <input
            id="pdf-file"
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={busy}
            className="block w-full text-sm"
          />
          <button
            disabled={!file || busy}
            className="bg-slate-900 text-white rounded px-4 py-2 disabled:opacity-50"
          >
            {busy ? "Uploading…" : "Upload & enqueue"}
          </button>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </form>

        {job && (
          <div className="bg-white border rounded-lg p-4 text-sm space-y-1">
            <p><span className="text-slate-500">job_id:</span> <code>{job.job_id}</code></p>
            <p><span className="text-slate-500">stream_id:</span> <code>{job.stream_id}</code></p>
            <p><span className="text-slate-500">status:</span> {status?.status || job.status}</p>
            {status?.chunks && <p><span className="text-slate-500">chunks:</span> {status.chunks}</p>}
            {status?.duration_s && <p><span className="text-slate-500">duration:</span> {status.duration_s}s</p>}
            {status?.error && <p className="text-red-600">{status.error}</p>}
          </div>
        )}
      </main>
    </div>
  );
}
