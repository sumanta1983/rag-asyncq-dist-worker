"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Nav from "@/components/Nav";
import { apiGet } from "@/lib/api";
import { getToken } from "@/lib/auth";

type Item = {
  id: number;
  endpoint: string;
  query: string;
  answer: string | null;
  model: string | null;
  created_at: string;
};

export default function HistoryPage() {
  const router = useRouter();
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    apiGet<Item[]>("/history/queries")
      .then(setItems)
      .catch((e: Error) => setError(e.message));
  }, [router]);

  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-6 space-y-4">
        <h1 className="text-xl font-semibold">Your queries</h1>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {items === null && !error && <p className="text-slate-500 text-sm">Loading…</p>}
        {items?.length === 0 && <p className="text-slate-500 text-sm">Nothing yet.</p>}
        <ul className="space-y-3">
          {items?.map((it) => (
            <li key={it.id} className="bg-white border rounded p-3 text-sm">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>{it.endpoint}{it.model ? ` · ${it.model}` : ""}</span>
                <span>{new Date(it.created_at).toLocaleString()}</span>
              </div>
              <p className="mt-1 font-medium">{it.query}</p>
              {it.answer && (
                <p className="mt-2 text-slate-700 whitespace-pre-wrap">{it.answer}</p>
              )}
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
