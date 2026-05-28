"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { CurrentUser, clearSession, getUser } from "@/lib/auth";

export default function Nav() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);

  useEffect(() => setUser(getUser()), []);

  if (!user) return null;

  return (
    <header className="border-b bg-white">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center gap-6">
        <Link href="/chat" className="font-semibold">RAG Async</Link>
        <Link href="/chat" className="text-sm text-slate-600 hover:text-slate-900">Chat</Link>
        <Link href="/history" className="text-sm text-slate-600 hover:text-slate-900">History</Link>
        {user.role === "admin" && (
          <Link href="/admin/ingest" className="text-sm text-slate-600 hover:text-slate-900">
            Ingest (admin)
          </Link>
        )}
        <span className="ml-auto text-sm text-slate-500">
          {user.name} · <span className="uppercase tracking-wider text-xs">{user.role}</span>
        </span>
        <button
          onClick={() => { clearSession(); router.push("/login"); }}
          className="text-sm text-red-600 hover:underline"
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
