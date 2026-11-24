"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 10) {
      setError("Use at least 10 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    // The link in the email signs the user in for recovery; we then set the new password.
    const { error } = await getSupabase().auth.updateUser({ password });
    setBusy(false);
    if (error) setError("This reset link has expired. Request a new one.");
    else router.replace("/app");
  }

  return (
    <AuthCard title="Choose a new password">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="New password" hint="At least 10 characters.">
          <Input
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          Save password
        </Button>
      </form>
    </AuthCard>
  );
}
