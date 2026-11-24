"use client";

import { getAccessToken } from "./supabase";
import type { EmergencyRule } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : "Something went wrong";
    throw new ApiError(detail, res.status);
  }
  return body as T;
}

export const send = (path: string, method: string, body?: unknown) =>
  api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export type Business = {
  id: string;
  name: string;
  contact_email: string | null;
  contact_phone: string | null;
  notification_email: string | null;
  address: string | null;
  website: string | null;
  timezone: string;
  transfer_number: string | null;
  fallback_number: string | null;
  emergency_number: string | null;
  transfer_mode?: string;
  transfer_in_hours: boolean;
  transfer_after_hours: boolean;
  transfer_emergencies_after_hours: boolean;
  emergency_preference: string;
  after_hours_message: string | null;
  unavailable_message?: string | null;
  emergency_rules: EmergencyRule[];
  service_status: string;
  included_minutes: number;
  current_period_start: string | null;
  current_period_end: string | null;
};

export type Me = {
  user: { id: string; email: string | null };
  business: Business | null;
  is_admin: boolean;
};
