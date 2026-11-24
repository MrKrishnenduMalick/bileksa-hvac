"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Button, Card, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { DEMO, warmApi, type DemoInfo } from "@/lib/demo";
import { getSupabase } from "@/lib/supabase";

export function DemoSignIn() {
  const router = useRouter();
  const [info, setInfo] = useState<DemoInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!DEMO) return;
    warmApi();
    let alive = true;
    // The free API host may be waking up: retry for about a minute.
    (async () => {
      for (let i = 0; i < 12 && alive; i++) {
        try {
          const d = await api<DemoInfo>("/public/demo");
          if (alive) setInfo(d);
          return;
        } catch {
          await new Promise((r) => setTimeout(r, 5000));
        }
      }
      if (alive) setError("The demo server is not responding right now. Please try again later.");
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (!DEMO) return <Alert tone="amber">The demo is not enabled on this site.</Alert>;
  if (error) return <Alert>{error}</Alert>;
  if (!info) return <Spinner label="Waking the demo server" />;

  async function signIn(kind: "owner" | "admin") {
    if (!info) return;
    setBusy(kind);
    setError(null);
    try {
      const auth = getSupabase().auth;
      await auth.signOut();
      const { error } = await auth.signInWithPassword(info[kind]);
      if (error) throw error;
      router.replace(kind === "admin" ? "/admin" : "/app");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sign in");
      setBusy(null);
    }
  }

  return (
    <div className="mt-8 grid gap-4 sm:grid-cols-2">
      {(
        [
          ["owner", "Business owner", "Dashboard, calls, leads, callbacks, usage, AI receptionist"],
          ["admin", "BILEKSA admin", "Clients, packages, payments, costs, Vapi, demo controls"],
        ] as const
      ).map(([kind, title, text]) => (
        <Card key={kind}>
          <h2 className="font-semibold text-navy">{title}</h2>
          <p className="mt-1 text-sm text-slate-600">{text}</p>
          <p className="mt-3 font-mono text-xs text-slate-500">{info[kind].email}</p>
          <Button className="mt-4 w-full" disabled={!!busy} onClick={() => signIn(kind)}>
            {busy === kind ? "Signing in…" : `Enter as ${title.toLowerCase()}`}
          </Button>
        </Card>
      ))}
    </div>
  );
}
