"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, Field, Input, Select } from "../ui";
import { send } from "@/lib/api";
import type { ClientDetail } from "@/lib/admin-types";
import { dateTime, label, phone } from "@/lib/format";

/** Vapi assistant + phone number: provisioning, number assignment, routing sync, test call. */
export function PhonePanel({
  base,
  detail,
  onChanged,
}: {
  base: string;
  detail: ClientDetail;
  onChanged: () => Promise<void>;
}) {
  const line = detail.phone;
  const a = detail.assistant;
  const [form, setForm] = useState({
    business_number: line?.business_number ?? "",
    carrier: line?.carrier ?? "other",
    forwarding_mode: line?.forwarding_mode ?? "conditional",
    provider: (line?.phone_provider ?? "vapi") as string,
    twilio_number: line?.phone_provider === "twilio" ? (line?.destination_number ?? "") : "",
  });
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ tone: "green", text: ok });
      await onChanged();
    } catch (err) {
      setMsg({ tone: "red", text: err instanceof Error ? err.message : "Failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      {detail.usage.included_minutes === 0 && (
        <Alert tone="amber">
          This client has no minutes yet, so calls are forwarded without the AI. Assign a package
          (Overview tab) before placing the test call.
        </Alert>
      )}
      <Card>
        <h2 className="mb-3 font-semibold text-navy">Vapi assistant</h2>
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs uppercase text-slate-500">State</dt>
            <dd>{label(a.state)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Assistant ID</dt>
            <dd className="font-mono text-xs">{a.vapi_assistant_id ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Template</dt>
            <dd>
              v{a.template_version ?? "—"}{" "}
              {a.template_version !== a.current_template_version && (
                <Badge tone="amber">update to v{a.current_template_version} pending</Badge>
              )}
            </dd>
          </div>
        </dl>
        {a.last_error && <p className="mt-2 text-sm text-red-700">{a.last_error}</p>}
        <Button
          className="mt-4"
          variant="secondary"
          disabled={busy}
          onClick={() =>
            act(
              () => send(`${base}/provision`, "POST"),
              "Provisioning queued; refresh in a moment.",
            )
          }
        >
          Re-sync assistant from the master template
        </Button>
      </Card>
      <Card>
        <h2 className="mb-1 font-semibold text-navy">Phone number</h2>
        <p className="mb-4 text-sm text-slate-600">
          BILEKSA assigns a number the client forwards their business line to: a Vapi number, or a
          cheaper Twilio number BILEKSA bought and imports into Vapi. Either way the number has no
          fixed assistant: every call is checked against the client&apos;s status and minute limit
          first, and transfers go to the client&apos;s own transfer number.
        </p>
        <form
          className="grid gap-4 sm:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault();
            const body = form.provider === "twilio" ? form : { ...form, twilio_number: undefined };
            act(() => send(`${base}/phone`, "POST", body), "Phone number saved.");
          }}
        >
          <Field label="Client's business number">
            <Input
              type="tel"
              required
              value={form.business_number}
              onChange={(e) => setForm({ ...form, business_number: e.target.value })}
            />
          </Field>
          <Field label="Carrier">
            <Select
              value={form.carrier}
              onChange={(e) => setForm({ ...form, carrier: e.target.value })}
            >
              {["att", "verizon", "tmobile", "comcast", "ringcentral", "other"].map((c) => (
                <option key={c} value={c}>
                  {c === "att" ? "AT&T" : label(c)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Forwarding">
            <Select
              value={form.forwarding_mode}
              onChange={(e) => setForm({ ...form, forwarding_mode: e.target.value })}
            >
              <option value="conditional">When busy / unanswered</option>
              <option value="all">All calls</option>
            </Select>
          </Field>
          <Field label="Number source">
            <Select
              value={form.provider}
              onChange={(e) => setForm({ ...form, provider: e.target.value })}
            >
              <option value="vapi">New Vapi number</option>
              <option value="twilio">Import a Twilio number</option>
            </Select>
          </Field>
          {form.provider === "twilio" && (
            <Field label="Twilio number (E.164)" hint="Bought in BILEKSA's Twilio account">
              <Input
                type="tel"
                required
                placeholder="+17135550100"
                value={form.twilio_number}
                onChange={(e) => setForm({ ...form, twilio_number: e.target.value })}
              />
            </Field>
          )}
          <div className="flex items-end">
            <Button type="submit" disabled={busy}>
              {line?.destination_number
                ? "Update"
                : form.provider === "twilio"
                  ? "Import Twilio number"
                  : "Assign Vapi number"}
            </Button>
          </div>
        </form>
        {line && (
          <div className="mt-6 space-y-3 text-sm">
            <p>
              Forward {phone(line.business_number)} to{" "}
              <span className="font-semibold">{phone(line.destination_number)}</span> ·{" "}
              <Badge tone={line.state === "verified" ? "green" : "amber"}>
                {label(line.state)}
              </Badge>{" "}
              {line.routing_synced ? (
                <Badge tone="green">Routing synced {dateTime(line.synced_at)}</Badge>
              ) : (
                <Badge tone="red">Routing not synced</Badge>
              )}
            </p>
            {line.last_error && <p className="text-red-700">{line.last_error}</p>}
            <ol className="list-decimal space-y-1 pl-5 text-slate-700">
              {line.steps.map((s) => (
                <li key={s}>{s.replace(/\*\*/g, "")}</li>
              ))}
            </ol>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  act(
                    () => send(`${base}/phone/sync`, "POST"),
                    "Routing pushed to Vapi and verified.",
                  )
                }
              >
                Sync routing to Vapi
              </Button>
              {line.state !== "verified" && (
                <Button
                  disabled={busy}
                  onClick={() =>
                    act(
                      () => send(`${base}/phone/test`, "POST"),
                      "Test window open for 15 minutes: call the business number now.",
                    )
                  }
                >
                  Start test call
                </Button>
              )}
            </div>
            {line.test_window_until && line.state === "testing" && (
              <p className="text-amber-800">
                Waiting for a test call until {dateTime(line.test_window_until)}.
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
