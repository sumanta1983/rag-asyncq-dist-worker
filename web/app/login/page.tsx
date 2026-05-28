"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiPostJson } from "@/lib/api";
import { CurrentUser, saveSession } from "@/lib/auth";

type LoginResp = { access_token: string; user: CurrentUser };

export default function LoginPage() {
  const router = useRouter();
  const [mobile, setMobile] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const resp = await apiPostJson<LoginResp>("/auth/login", { mobile, password });
      saveSession(resp.access_token, resp.user);
      router.replace(resp.user.role === "admin" ? "/admin/ingest" : "/chat");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen grid place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-lg border p-6 space-y-4">
        <h1 className="text-xl font-semibold">Sign in</h1>

        <label className="block text-sm">
          <span className="text-slate-600">Mobile</span>
          <input
            value={mobile}
            onChange={(e) => setMobile(e.target.value)}
            placeholder="9876543210"
            className="mt-1 w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
            required
          />
        </label>

        <label className="block text-sm">
          <span className="text-slate-600">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
            required
          />
        </label>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          disabled={busy}
          className="w-full bg-slate-900 text-white rounded py-2 disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="text-sm text-slate-600">
          No account?{" "}
          <Link href="/register" className="text-slate-900 underline">
            Register
          </Link>
        </p>
      </form>
    </main>
  );
}
