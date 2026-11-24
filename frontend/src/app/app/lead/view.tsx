"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { UrgencyBadge } from "@/components/badges";
import { Alert, Button, Card, Field, Input, PageHeader, Select, Spinner } from "@/components/ui";
import { api, send } from "@/lib/api";
import { dateTime, label, phone } from "@/lib/format";
import { LEAD_STATUSES, type CallRow, type Lead } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

type Detail = Lead & {
  call: CallRow | null;
  timeline: { kind: string; detail: string | null; actor: string; at: string }[];
};

export function LeadDetailPage() {
  const id = useSearchParams().get("id") ?? "";
  const { data, error, loading, reload } = useLoad(() => api<Detail>(`/api/leads/${id}`), [id]);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  async function update(body: Record<string, string>) {
    setMsg(null);
    try {
      await send(`/api/leads/${id}`, "PATCH", body);
      setNote("");
      await reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not save");
    }
  }

  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error ?? "Lead not found"}</Alert>;

  return (
    <>
      <PageHeader
        title={data.customer_name ?? "Unknown caller"}
        subtitle={`Captured ${dateTime(data.created_at)} · ${label(data.source)}`}
      />
      {msg && <Alert>{msg}</Alert>}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {[
              [
                "Callback number",
                `${phone(data.callback_number)}${data.callback_number && !data.number_confirmed ? " (not confirmed)" : ""}`,
              ],
              ["Address", data.address],
              ["ZIP code", data.zip_code],
              ["Service", label(data.service_type)],
              ["Equipment", label(data.equipment_type)],
              ["Customer", label(data.customer_type)],
              ["HVAC issue", data.issue_summary],
              ["Notes", data.notes],
              [
                "Appointment",
                data.appointment_status === "none"
                  ? "Not requested"
                  : `${label(data.appointment_status)}${data.preferred_appointment ? ` · prefers ${data.preferred_appointment}` : ""}`,
              ],
              [
                "Callback",
                data.callback_status === "none"
                  ? "Not requested"
                  : `${label(data.callback_status)}${data.callback_preferred_time ? ` · prefers ${data.callback_preferred_time}` : ""}`,
              ],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs uppercase tracking-wide text-slate-500">{k}</dt>
                <dd className="mt-0.5 text-sm text-slate-900">{v || "—"}</dd>
              </div>
            ))}
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Urgency</dt>
              <dd className="mt-1">
                <UrgencyBadge urgency={data.urgency} />
              </dd>
            </div>
          </dl>
        </Card>
        <Card>
          <Field label="Lead status">
            <Select value={data.status} onChange={(e) => update({ status: e.target.value })}>
              {LEAD_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {label(s)}
                </option>
              ))}
            </Select>
          </Field>
          {data.callback_status === "requested" && (
            <Button className="mt-4 w-full" onClick={() => update({ callback_status: "done" })}>
              Mark callback done
            </Button>
          )}
          <form
            className="mt-4 space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (note.trim()) update({ note });
            }}
          >
            <Field label="Add a note">
              <Input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <Button variant="secondary" type="submit" className="w-full">
              Save note
            </Button>
          </form>
        </Card>
      </div>
      <Card className="mt-6">
        <h2 className="mb-3 font-semibold text-navy">Timeline</h2>
        <ol className="space-y-3 border-l border-slate-200 pl-4">
          {data.timeline.map((e, i) => (
            <li key={i} className="text-sm">
              <p className="font-medium text-slate-900">{label(e.kind)}</p>
              <p className="text-slate-600">{e.detail}</p>
              <p className="text-xs text-slate-400">
                {dateTime(e.at)} · {e.actor.startsWith("user:") ? "Your team" : "AI receptionist"}
              </p>
            </li>
          ))}
        </ol>
      </Card>
    </>
  );
}
