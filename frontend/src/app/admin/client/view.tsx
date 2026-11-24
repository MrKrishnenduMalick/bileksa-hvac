"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { ClientProfile } from "@/components/admin/client-profile";
import { EmergencyEditor } from "@/components/admin/emergency-editor";
import { PaymentsPanel } from "@/components/admin/payments-panel";
import { PhonePanel } from "@/components/admin/phone-panel";
import { ServicePanel } from "@/components/admin/service-panel";
import { ServiceStatusBadge } from "@/components/badges";
import { CallsTable } from "@/components/calls-table";
import { AreasEditor } from "@/components/editors/areas-editor";
import { FaqsEditor } from "@/components/editors/faqs-editor";
import { HoursEditor } from "@/components/editors/hours-editor";
import { ServicesEditor } from "@/components/editors/services-editor";
import { Alert, Button, Card, Empty, Field, Input, PageHeader, Spinner } from "@/components/ui";
import { api, send } from "@/lib/api";
import type { ClientDetail } from "@/lib/admin-types";
import { useLoad } from "@/lib/use-load";

const TABS = [
  ["overview", "Overview"],
  ["profile", "Business & routing"],
  ["services", "Services"],
  ["areas", "Service areas"],
  ["hours", "Hours"],
  ["faqs", "FAQs"],
  ["emergency", "Emergency"],
  ["phone", "Phone & Vapi"],
  ["payments", "Payments"],
] as const;
type Tab = (typeof TABS)[number][0];

function Invite({ base, onDone }: { base: string; onDone: () => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setMsg(null);
        try {
          await send(`${base}/invite`, "POST", { email });
          setMsg({ tone: "green", text: `Invitation sent to ${email}.` });
          setEmail("");
          await onDone();
        } catch (err) {
          setMsg({ tone: "red", text: err instanceof Error ? err.message : "Could not invite" });
        }
      }}
    >
      <Field label="Invite the client owner by email">
        <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Button type="submit" variant="secondary">
        Send invitation
      </Button>
      {msg && (
        <div className="w-full">
          <Alert tone={msg.tone}>{msg.text}</Alert>
        </div>
      )}
    </form>
  );
}

export function ClientPage() {
  const id = useSearchParams().get("id") ?? "";
  const base = `/admin/api/clients/${id}`;
  const { data, error, loading, reload } = useLoad(() => api<ClientDetail>(base), [id]);
  const [tab, setTab] = useState<Tab>("overview");

  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error ?? "Client not found"}</Alert>;
  const b = data.business;
  const done = data.readiness.filter((s) => s.done).length;

  return (
    <>
      <PageHeader
        title={b.name}
        subtitle={`${done} of ${data.readiness.length} onboarding steps complete`}
        action={
          <div className="flex items-center gap-3">
            <ServiceStatusBadge status={b.service_status} />
            <Link href="/admin" className="text-sm text-brand hover:underline">
              All clients
            </Link>
          </div>
        }
      />
      <nav aria-label="Client sections" className="mb-6 flex flex-wrap gap-1">
        {TABS.map(([key, text]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            aria-current={tab === key ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm ${tab === key ? "bg-navy text-white" : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"}`}
          >
            {text}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <div className="space-y-6">
          <ServicePanel clientId={id} usage={data.usage} onChanged={reload} />
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <h2 className="mb-3 font-semibold text-navy">Onboarding checklist</h2>
              <ol className="space-y-1 text-sm">
                {data.readiness.map((s, i) => (
                  <li key={s.step} className="flex gap-2">
                    <span aria-hidden className={s.done ? "text-green-700" : "text-slate-400"}>
                      {s.done ? "✓" : "○"}
                    </span>
                    <span className={s.done ? "" : "text-slate-600"}>
                      {i + 1}. {s.step}
                    </span>
                  </li>
                ))}
              </ol>
            </Card>
            <Card>
              <h2 className="mb-3 font-semibold text-navy">Client accounts</h2>
              {data.members.length === 0 ? (
                <p className="mb-4 text-sm text-slate-600">No owner account yet.</p>
              ) : (
                <ul className="mb-4 text-sm text-slate-700">
                  {data.members.map((m) => (
                    <li key={m.user_id}>
                      {m.role} · <span className="font-mono text-xs">{m.user_id}</span>
                    </li>
                  ))}
                </ul>
              )}
              <Invite base={base} onDone={reload} />
            </Card>
          </div>
          <Card>
            <h2 className="mb-3 font-semibold text-navy">Recent calls</h2>
            {data.recent_calls.length === 0 ? (
              <Empty title="No calls yet" />
            ) : (
              <CallsTable calls={data.recent_calls} leadLinks={false} />
            )}
          </Card>
        </div>
      )}
      {tab === "profile" && <ClientProfile base={base} business={b} onSaved={reload} />}
      {tab === "services" && <ServicesEditor base={base} />}
      {tab === "areas" && <AreasEditor base={base} />}
      {tab === "hours" && <HoursEditor base={base} />}
      {tab === "faqs" && <FaqsEditor base={base} />}
      {tab === "emergency" && (
        <EmergencyEditor base={base} rules={b.emergency_rules} onSaved={reload} />
      )}
      {tab === "phone" && <PhonePanel base={base} detail={data} onChanged={reload} />}
      {tab === "payments" && <PaymentsPanel base={base} />}
    </>
  );
}
