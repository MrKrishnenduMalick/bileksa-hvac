"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ServiceStatusBadge, UsageBar } from "@/components/badges";
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Field,
  Input,
  PageHeader,
  Spinner,
  Table,
  Td,
} from "@/components/ui";
import { api, send } from "@/lib/api";
import type { ClientRow } from "@/lib/admin-types";
import { label } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function ClientsPage() {
  const router = useRouter();
  const { data, error, loading } = useLoad(() => api<ClientRow[]>("/admin/api/clients"));
  const [form, setForm] = useState({
    name: "",
    contact_email: "",
    contact_phone: "",
    timezone: "America/Chicago",
  });
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    setBusy(true);
    try {
      const b = (await send("/admin/api/clients", "POST", {
        ...form,
        contact_email: form.contact_email || null,
        contact_phone: form.contact_phone || null,
      })) as { id: string };
      router.push(`/admin/client?id=${b.id}`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not create the client");
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Clients"
        subtitle="Every HVAC client is created, configured and activated here by BILEKSA."
      />
      <Card className="mb-6">
        <h2 className="mb-3 font-semibold text-navy">Create a client</h2>
        <form onSubmit={create} className="grid gap-4 sm:grid-cols-4">
          <Field label="Business name">
            <Input
              required
              minLength={2}
              maxLength={120}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <Field label="Contact email">
            <Input
              type="email"
              value={form.contact_email}
              onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
            />
          </Field>
          <Field label="Contact phone">
            <Input
              type="tel"
              value={form.contact_phone}
              onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
            />
          </Field>
          <Field label="Time zone">
            <Input
              value={form.timezone}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            />
          </Field>
          <div className="space-y-3 sm:col-span-4">
            {msg && <Alert>{msg}</Alert>}
            <Button type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create client"}
            </Button>
          </div>
        </form>
      </Card>
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No clients yet" />
        ) : (
          <Table head={["Client", "Status", "Package", "Usage", "Assistant", "Phone", "Requests"]}>
            {data.map((c) => (
              <tr key={c.id}>
                <Td>
                  <Link
                    className="font-medium text-brand hover:underline"
                    href={`/admin/client?id=${c.id}`}
                  >
                    {c.name}
                  </Link>
                </Td>
                <Td>
                  <ServiceStatusBadge status={c.service_status} />
                  {c.approaching_limit && (
                    <span className="mt-1 block text-xs text-amber-700">Approaching limit</span>
                  )}
                </Td>
                <Td>{c.package?.name ?? "—"}</Td>
                <Td className="min-w-[9rem]">
                  <p className="text-xs text-slate-600">
                    {c.used_minutes} / {c.included_minutes} min
                  </p>
                  <UsageBar percent={c.usage_percent} />
                </Td>
                <Td>
                  {label(c.assistant_state)}
                  {c.assistant_error && (
                    <span className="block text-xs text-red-700">{c.assistant_error}</span>
                  )}
                </Td>
                <Td>{label(c.phone_state)}</Td>
                <Td>
                  {c.open_upgrade_requests > 0 ? (
                    <Badge tone="blue">{c.open_upgrade_requests} open</Badge>
                  ) : (
                    "—"
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
