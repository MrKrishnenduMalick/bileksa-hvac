"use client";

import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Empty,
  Field,
  Input,
  SectionHeader,
  Spinner,
  Table,
  Td,
} from "@/components/ui";
import { api, send } from "@/lib/api";
import { money } from "@/lib/format";
import type { Service } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

const blank = { name: "", description: "", min: "", max: "", price_note: "", available: true };
const cents = (v: string) => (v.trim() === "" ? null : Math.round(parseFloat(v) * 100));

export function ServicesEditor({ base }: { base: string }) {
  const { data, error, loading, reload } = useLoad(
    () => api<Service[]>(`${base}/services`),
    [base],
  );
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  function edit(s: Service) {
    setEditing(s.id);
    setForm({
      name: s.name,
      description: s.description ?? "",
      min: s.price_min_cents == null ? "" : String(s.price_min_cents / 100),
      max: s.price_max_cents == null ? "" : String(s.price_max_cents / 100),
      price_note: s.price_note ?? "",
      available: s.available,
    });
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    const body = {
      name: form.name,
      description: form.description || null,
      price_min_cents: cents(form.min),
      price_max_cents: cents(form.max),
      price_note: form.price_note || null,
      available: form.available,
    };
    try {
      if (editing) await send(`${base}/services/${editing}`, "PATCH", body);
      else await send(`${base}/services`, "POST", body);
      setForm(blank);
      setEditing(null);
      await reload();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not save");
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Remove this service? Your receptionist will stop offering it.")) return;
    await send(`${base}/services/${id}`, "DELETE");
    await reload();
  }

  return (
    <>
      <SectionHeader
        title="HVAC services"
        subtitle="Your receptionist only quotes the services and approved price ranges listed here."
      />
      <Card className="mb-6">
        <h2 className="mb-3 font-semibold text-navy">
          {editing ? "Edit service" : "Add a service"}
        </h2>
        {msg && (
          <div className="mb-3">
            <Alert>{msg}</Alert>
          </div>
        )}
        <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
          <Field label="Service name">
            <Input
              required
              maxLength={120}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="AC repair"
            />
          </Field>
          <Field label="Description (optional)">
            <Input
              maxLength={500}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Field>
          <Field label="Price from ($)">
            <Input
              type="number"
              min="0"
              step="0.01"
              value={form.min}
              onChange={(e) => setForm({ ...form, min: e.target.value })}
            />
          </Field>
          <Field label="Price up to ($)">
            <Input
              type="number"
              min="0"
              step="0.01"
              value={form.max}
              onChange={(e) => setForm({ ...form, max: e.target.value })}
            />
          </Field>
          <Field label="Price note (optional)" hint='e.g. "diagnostic fee waived with repair"'>
            <Input
              maxLength={200}
              value={form.price_note}
              onChange={(e) => setForm({ ...form, price_note: e.target.value })}
            />
          </Field>
          <div className="flex items-end">
            <Checkbox
              label="Currently available"
              checked={form.available}
              onChange={(e) => setForm({ ...form, available: e.target.checked })}
            />
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit">{editing ? "Save service" : "Add service"}</Button>
            {editing && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setEditing(null);
                  setForm(blank);
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      </Card>
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No services yet">
            Until you add services, your receptionist tells callers the team will confirm.
          </Empty>
        ) : (
          <Table head={["Service", "Price range", "Note", "Status", ""]}>
            {data.map((s) => (
              <tr key={s.id}>
                <Td>
                  <p className="font-medium">{s.name}</p>
                  {s.description && <p className="text-xs text-slate-500">{s.description}</p>}
                </Td>
                <Td>
                  {s.price_min_cents == null && s.price_max_cents == null
                    ? "—"
                    : s.price_min_cents === s.price_max_cents
                      ? money(s.price_min_cents)
                      : `${money(s.price_min_cents)} – ${money(s.price_max_cents)}`}
                </Td>
                <Td>{s.price_note ?? "—"}</Td>
                <Td>
                  {s.available ? <Badge tone="green">Available</Badge> : <Badge>Paused</Badge>}
                </Td>
                <Td className="whitespace-nowrap text-right">
                  <Button variant="secondary" onClick={() => edit(s)}>
                    Edit
                  </Button>{" "}
                  <Button variant="danger" onClick={() => remove(s.id)}>
                    Remove
                  </Button>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
