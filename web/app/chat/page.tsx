"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import Nav from "@/components/Nav";
import { apiPostJson } from "@/lib/api";
import { getToken } from "@/lib/auth";

type Source = { page: string; source: string };
type ChatResp = { query: string; answer: string; model: string; sources: Source[] };
type Turn = { role: "user" | "assistant"; text: string; sources?: Source[] };

export default function ChatPage() {
  const router = useRouter();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, busy]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q) return;
    setTurns((t) => [...t, { role: "user", text: q }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const resp = await apiPostJson<ChatResp>("/chat", { query: q });
      setTurns((t) => [...t, { role: "assistant", text: resp.answer, sources: resp.sources }]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "chat failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-6 flex flex-col">
        <div ref={scrollerRef} className="flex-1 overflow-y-auto space-y-4">
          {turns.length === 0 && (
            <p className="text-slate-500 text-sm">Ask a question about the indexed documents.</p>
          )}
          {turns.map((t, i) => (
            <div
              key={i}
              className={`p-3 rounded-lg ${t.role === "user" ? "bg-slate-900 text-white ml-12" : "bg-white border mr-12"}`}
            >
              <div className="whitespace-pre-wrap">{t.text}</div>
              {t.sources && t.sources.length > 0 && (
                <ul className="mt-2 text-xs text-slate-500 space-y-0.5">
                  {t.sources.map((s, j) => (
                    <li key={j}>
                      page {s.page} — {s.source}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          {busy && (
            <div className="p-3 rounded-lg bg-white border mr-12 text-slate-400 italic">
              thinking…
            </div>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>

        <form onSubmit={send} className="mt-4 flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your question…"
            className="flex-1 border rounded px-3 py-2 bg-white"
            disabled={busy}
          />
          <button
            disabled={busy || !input.trim()}
            className="bg-slate-900 text-white rounded px-4 disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </main>
    </div>
  );
}
