"use client";

import Link from "next/link";
import { useState } from "react";
import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    // Always show the same message so this form can't be used to discover accounts.
    await getSupabase().auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
    });
    setSent(true);
    setBusy(false);
  }

  return (
    <AuthCard
      title="Reset your password"
      subtitle="We'll email you a link to choose a new password."
    >
      {sent ? (
        <Alert tone="green">If an account exists for {email}, a reset link is on its way.</Alert>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Email">
            <Input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={busy} className="w-full">
            Send reset link
          </Button>
        </form>
      )}
      <p className="mt-4 text-center text-sm">
        <Link href="/login" className="text-brand hover:underline">
          Back to sign in
        </Link>
      </p>
    </AuthCard>
  );
}
