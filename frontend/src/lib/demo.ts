/** True only on the public demo build (NEXT_PUBLIC_DEMO_MODE=true). The backend enforces the
 * demo rules itself; this flag only changes what the UI shows. */
export const DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export type DemoInfo = {
  company: string;
  owner: { email: string; password: string };
  admin: { email: string; password: string };
  scenarios: Record<string, string>;
  note: string;
};

export type VoiceStatus = {
  mode: "live" | "simulation";
  reason: string | null;
  budget_usd: number;
  spent_usd: number;
  remaining_usd: number;
  calls_today: number;
  max_calls_per_day: number;
  max_call_seconds: number;
  enabled: boolean;
  budget_cap_usd: number;
  paused_until: string | null;
};

/** Wake the API early: on the free host it may be asleep. Fire-and-forget. */
export function warmApi() {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  fetch(`${base}/health`, { cache: "no-store" }).catch(() => undefined);
}
