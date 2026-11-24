"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Button, Field, Input } from "../ui";

/** Confirms a sensitive service change with the admin's password. The password is sent to
 * the backend, which verifies it with Supabase Auth; the browser never decides. */
export function PasswordDialog({
  summary,
  onConfirm,
  onCancel,
}: {
  summary: string;
  onConfirm: (password: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onConfirm(password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply the change");
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-title"
      className="w-full max-w-md rounded-2xl p-0 shadow-xl backdrop:bg-slate-900/40"
      onCancel={onCancel}
    >
      <form onSubmit={submit} className="space-y-4 p-6">
        <h2 id="confirm-title" className="text-lg font-semibold text-navy">
          Confirm change
        </h2>
        <p className="whitespace-pre-line text-sm text-slate-700">{summary}</p>
        <Field label="Your password" hint="Required for package, limit and service changes.">
          <Input
            type="password"
            autoComplete="current-password"
            required
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <div className="flex gap-2">
          <Button type="submit" disabled={busy}>
            {busy ? "Checking…" : "Confirm"}
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </dialog>
  );
}
