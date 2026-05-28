"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiPostJson } from "@/lib/api";
import { CurrentUser, saveSession } from "@/lib/auth";

type RegisterResp = { access_token: string; user: CurrentUser };

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    setBusy(true);
    try {
      const resp = await apiPostJson<RegisterResp>("/auth/register", {
        name,
        mobile,
        password,
        confirm_password: confirmPassword,
      });
      saveSession(resp.access_token, resp.user);
      router.replace("/chat");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen grid place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-lg border p-6 space-y-4">
        <h1 className="text-xl font-semibold">Create account</h1>

        <label className="block text-sm">
          <span className="text-slate-600">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full border rounded px-3 py-2"
            required
            minLength={1}
          />
        </label>

        <label className="block text-sm">
          <span className="text-slate-600">Mobile (10-digit Indian number)</span>
          <input
            value={mobile}
            onChange={(e) => setMobile(e.target.value)}
            placeholder="9876543210"
            className="mt-1 w-full border rounded px-3 py-2"
            required
          />
        </label>

        <label className="block text-sm">
          <span className="text-slate-600">Password (min 8 chars)</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full border rounded px-3 py-2"
            required
            minLength={8}
          />
        </label>

        <label className="block text-sm">
          <span className="text-slate-600">Confirm password</span>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="mt-1 w-full border rounded px-3 py-2"
            required
            minLength={8}
          />
        </label>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          disabled={busy}
          className="w-full bg-slate-900 text-white rounded py-2 disabled:opacity-50"
        >
          {busy ? "Creating…" : "Register"}
        </button>

        <p className="text-sm text-slate-600">
          Already registered?{" "}
          <Link href="/login" className="text-slate-900 underline">
            Sign in
          </Link>
        </p>
      </form>
    </main>
  );
}
