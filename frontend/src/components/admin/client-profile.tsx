"use client";

import { useState } from "react";
import { Alert, Button, Card, Checkbox, Field, Input, Select } from "../ui";
import { send, type Business } from "@/lib/api";

type Fields = Record<string, string | boolean | null>;
const TEXT = [
  "name",
  "contact_email",
  "contact_phone",
  "notification_email",
  "address",
  "website",
  "timezone",
  "transfer_number",
  "fallback_number",
  "emergency_number",
  "after_hours_message",
  "unavailable_message",
] as const;
const BOOL = [
  "transfer_in_hours",
  "transfer_after_hours",
  "transfer_emergencies_after_hours",
] as const;

/** Business information, routing numbers and transfer rules (admin). Saves changed fields. */
export function ClientProfile({
  base,
  business,
  onSaved,
}: {
  base: string;
  business: Business & { transfer_mode: string; unavailable_message: string | null };
  onSaved: () => Promise<void>;
}) {
  const initial: Fields = Object.fromEntries(
    [...TEXT, ...BOOL, "transfer_mode", "emergency_preference"].map((k) => [
      k,
      (business as unknown as Fields)[k] ?? null,
    ]),
  );
  const [v, setV] = useState<Fields>(initial);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const set = (k: string, value: string | boolean) => setV((p) => ({ ...p, [k]: value }));
  const text = (k: string) => (v[k] as string | null) ?? "";

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    const changed = Object.fromEntries(
      Object.entries(v)
        .filter(([k, val]) => val !== initial[k])
        .map(([k, val]) => [k, val === "" ? null : val]),
    );
    try {
      await send(base, "PATCH", changed);
      setMsg({
        tone: "green",
        text: "Saved. Phone routing and the assistant re-sync automatically.",
      });
      await onSaved();
    } catch (err) {
      setMsg({ tone: "red", text: err instanceof Error ? err.message : "Could not save" });
    }
  }

  const input = (k: string, labelText: string, hint?: string, type = "text") => (
    <Field label={labelText} hint={hint}>
      <Input type={type} value={text(k)} onChange={(e) => set(k, e.target.value)} />
    </Field>
  );

  return (
    <Card>
      <form onSubmit={save} className="space-y-6">
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <div>
          <h2 className="mb-3 font-semibold text-navy">Business information</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {input("name", "Business name")}
            {input("timezone", "Time zone", "e.g. America/Chicago")}
            {input("contact_email", "Contact email", undefined, "email")}
            {input("contact_phone", "Contact phone", undefined, "tel")}
            {input(
              "notification_email",
              "Owner notification email",
              "Leave empty to use the contact email.",
              "email",
            )}
            {input("website", "Website")}
            <div className="sm:col-span-2">{input("address", "Address")}</div>
          </div>
        </div>
        <div>
          <h2 className="mb-1 font-semibold text-navy">Transfers and fallback</h2>
          <p className="mb-3 text-sm text-slate-600">
            Use direct lines, never the number that forwards to the AI (that would loop). When the
            minute limit is reached or service is suspended, calls go to the transfer number, then
            the fallback number, then the unavailable message.
          </p>
          <div className="grid gap-4 sm:grid-cols-3">
            {input("transfer_number", "Transfer number (direct line)", undefined, "tel")}
            {input("fallback_number", "Fallback / backup number", undefined, "tel")}
            {input(
              "emergency_number",
              "Emergency transfer number",
              "Tried first for emergencies.",
              "tel",
            )}
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field
              label="Transfer mode"
              hint="Warm transfer returns the caller to the AI when nobody answers (Twilio/Vapi numbers only; verify with a live test)."
            >
              <Select
                value={text("transfer_mode") || "blind"}
                onChange={(e) => set("transfer_mode", e.target.value)}
              >
                <option value="blind">Blind transfer (most reliable)</option>
                <option value="warm">Warm transfer with fallback to the AI</option>
              </Select>
            </Field>
            <Field label="Emergency handling">
              <Select
                value={text("emergency_preference") || "transfer_then_callback"}
                onChange={(e) => set("emergency_preference", e.target.value)}
              >
                <option value="transfer_then_callback">
                  Try to transfer, then take a callback
                </option>
                <option value="callback_only">Urgent callback request only</option>
              </Select>
            </Field>
          </div>
          <div className="mt-4 space-y-2">
            <Checkbox
              label="Allow transfers during business hours"
              checked={!!v.transfer_in_hours}
              onChange={(e) => set("transfer_in_hours", e.target.checked)}
            />
            <Checkbox
              label="Allow transfers after hours"
              checked={!!v.transfer_after_hours}
              onChange={(e) => set("transfer_after_hours", e.target.checked)}
            />
            <Checkbox
              label="Allow emergency transfers after hours"
              checked={!!v.transfer_emergencies_after_hours}
              onChange={(e) => set("transfer_emergencies_after_hours", e.target.checked)}
            />
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {input(
              "after_hours_message",
              "After-hours message",
              "Read when nobody can take a transfer.",
            )}
            {input(
              "unavailable_message",
              "Unavailable-call message",
              "Spoken when the AI is off and no forwarding number exists.",
            )}
          </div>
        </div>
        <Button type="submit">Save changes</Button>
      </form>
    </Card>
  );
}
