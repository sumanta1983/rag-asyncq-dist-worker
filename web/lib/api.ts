"use client";

import { getToken } from "./auth";

const BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = await res.text().catch(() => null);
    }
    const detail =
      (body && typeof body === "object" && "detail" in body && (body as { detail?: string }).detail) ||
      `HTTP ${res.status}`;
    throw new ApiError(res.status, body, String(detail));
  }
  return res;
}

export async function apiGet<T>(path: string): Promise<T> {
  return (await request(path)).json();
}

export async function apiPostJson<T>(path: string, body: unknown): Promise<T> {
  return (await request(path, { method: "POST", body: JSON.stringify(body) })).json();
}

export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  return (await request(path, { method: "POST", body: form })).json();
}
