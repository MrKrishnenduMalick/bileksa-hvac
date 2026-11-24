"use client";

import { useEffect, useState, type ReactNode } from "react";
import { DEMO } from "@/lib/demo";
import { getSupabase } from "@/lib/supabase";
import { AuthCard } from "./auth-card";
import { Alert, Button, Field, Input, Spinner } from "./ui";

type Step =
  | { kind: "loading" }
  | { kind: "ok" }
  | { kind: "verify"; factorId: string }
  | { kind: "enroll"; factorId: string; qr: string; secret: string };

/** The admin API requires a multi-factor (aal2) session. This gate enrols or challenges an
 * authenticator app (TOTP) through Supabase Auth before showing the admin area. */
export function MfaGate({ children }: { children: ReactNode }) {
  // The public demo publishes its admin sign-in, so it cannot use an authenticator app.
  // The demo API runs with MFA off as well; client deployments always require it.
  if (DEMO) return <>{children}</>;
  return <MfaGateInner>{children}</MfaGateInner>;
}

function MfaGateInner({ children }: { children: ReactNode }) {
  const [step, setStep] = useState<Step>({ kind: "loading" });
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      const auth = getSupabase().auth;
      const { data: aal } = await auth.mfa.getAuthenticatorAssuranceLevel();
      if (aal?.currentLevel === "aal2") return { kind: "ok" } as Step;
      const { data: factors } = await auth.mfa.listFactors();
      const totp = factors?.totp?.[0];
      if (totp) return { kind: "verify", factorId: totp.id } as Step;
      const { data, error } = await auth.mfa.enroll({
        factorType: "totp",
        friendlyName: `BILEKSA admin ${Date.now()}`,
      });
      if (error || !data) throw error ?? new Error("Could not start enrolment");
      return {
        kind: "enroll",
        factorId: data.id,
        qr: data.totp.qr_code,
        secret: data.totp.secret,
      } as Step;
    })()
      .then((s) => alive && setStep(s))
      .catch(
        (e) => alive && setError(e instanceof Error ? e.message : "Multi-factor setup failed"),
      );
    return () => {
      alive = false;
    };
  }, []);

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    if (step.kind !== "verify" && step.kind !== "enroll") return;
    setBusy(true);
    setError(null);
    const { error } = await getSupabase().auth.mfa.challengeAndVerify({
      factorId: step.factorId,
      code: code.trim(),
    });
    setBusy(false);
    if (error)
      setError("That code didn't work. Check the time on your phone and try the newest code.");
    else setStep({ kind: "ok" });
  }

  if (step.kind === "ok") return <>{children}</>;
  if (step.kind === "loading")
    return error ? (
      <div className="mx-auto max-w-lg p-8">
        <Alert>{error}</Alert>
      </div>
    ) : (
      <Spinner />
    );
  return (
    <AuthCard
      title={step.kind === "enroll" ? "Set up two-step sign-in" : "Two-step sign-in"}
      subtitle="The BILEKSA admin area requires a code from your authenticator app."
    >
      <form onSubmit={verify} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        {step.kind === "enroll" && (
          <div className="space-y-2 text-sm text-slate-700">
            <p>
              Scan this QR code with an authenticator app (Google Authenticator, 1Password, Authy),
              then enter the 6-digit code.
            </p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={step.qr}
              alt="QR code for your authenticator app"
              className="mx-auto h-44 w-44 rounded-lg bg-white p-2"
            />
            <p className="break-all text-xs text-slate-500">
              Can&apos;t scan? Enter this key: {step.secret}
            </p>
          </div>
        )}
        <Field label="6-digit code">
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Checking…" : "Verify"}
        </Button>
      </form>
    </AuthCard>
  );
}
