"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { api, type Me } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { error } = await getSupabase().auth.signInWithPassword({ email, password });
      if (error) throw error;
      // BILEKSA staff without a client account go straight to the admin area.
      const me = await api<Me>("/api/me").catch(() => null);
      router.replace(me && me.is_admin && !me.business ? "/admin" : "/app");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Sign in" subtitle="Welcome back to your AI receptionist.">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Email">
          <Input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-center text-sm">
          <Link href="/forgot-password" className="text-slate-600 hover:text-brand hover:underline">
            Forgot your password?
          </Link>
        </p>
        <p className="text-center text-sm text-slate-600">
          New to BILEKSA?{" "}
          <Link href="/contact" className="font-medium text-brand hover:underline">
            Talk to our team
          </Link>{" "}
          — accounts are set up by BILEKSA.
        </p>
      </form>
    </AuthCard>
  );
}
