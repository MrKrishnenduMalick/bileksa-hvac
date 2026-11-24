"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, Empty, Field, Input, Select, Spinner, Table, Td } from "../ui";
import { api, send } from "@/lib/api";
import type { Payment } from "@/lib/admin-types";
import { day, label, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const today = () => new Date().toISOString().slice(0, 10);

/** Payments are taken outside the app and recorded here. Never shown to the client. */
export function PaymentsPanel({ base }: { base: string }) {
  const { data, error, loading, reload } = useLoad(
    () => api<Payment[]>(`${base}/payments`),
    [base],
  );
  const [f, setF] = useState({
    amount: "",
    payment_type: "subscription",
    paid_on: today(),
    status: "received",
    period_start: "",
    period_end: "",
    notes: "",
  });
  const [msg, setMsg] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      await send(`${base}/payments`, "POST", {
        amount_cents: Math.round(parseFloat(f.amount) * 100),
        payment_type: f.payment_type,
        paid_on: f.paid_on,
        status: f.status,
        period_start: f.period_start || null,
        period_end: f.period_end || null,
        notes: f.notes || null,
      });
      setF({ ...f, amount: "", notes: "" });
      await reload();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not record");
    }
  }

  return (
    <>
      <Card className="mb-6">
        <h2 className="font-semibold text-navy">Record a payment</h2>
        <p className="mb-4 mt-1 text-sm text-slate-600">
          Payments are arranged outside the app. Setup and build fees recorded here are never shown
          to the client.
        </p>
        <form onSubmit={add} className="grid gap-4 sm:grid-cols-4">
          <Field label="Amount ($)">
            <Input
              type="number"
              min="0.01"
              step="0.01"
              required
              value={f.amount}
              onChange={(e) => setF({ ...f, amount: e.target.value })}
            />
          </Field>
          <Field label="Type">
            <Select
              value={f.payment_type}
              onChange={(e) => setF({ ...f, payment_type: e.target.value })}
            >
              <option value="subscription">Monthly package</option>
              <option value="setup_fee">Setup / build fee</option>
              <option value="upgrade">Upgrade</option>
              <option value="other">Other</option>
            </Select>
          </Field>
          <Field label="Date">
            <Input
              type="date"
              required
              value={f.paid_on}
              onChange={(e) => setF({ ...f, paid_on: e.target.value })}
            />
          </Field>
          <Field label="Status">
            <Select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
              <option value="received">Received</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
              <option value="refunded">Refunded</option>
            </Select>
          </Field>
          <Field label="Period start">
            <Input
              type="date"
              value={f.period_start}
              onChange={(e) => setF({ ...f, period_start: e.target.value })}
            />
          </Field>
          <Field label="Period end">
            <Input
              type="date"
              value={f.period_end}
              onChange={(e) => setF({ ...f, period_end: e.target.value })}
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Notes">
              <Input
                maxLength={1000}
                value={f.notes}
                onChange={(e) => setF({ ...f, notes: e.target.value })}
              />
            </Field>
          </div>
          <div className="space-y-2 sm:col-span-4">
            {msg && <Alert>{msg}</Alert>}
            <Button type="submit">Record payment</Button>
          </div>
        </form>
      </Card>
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No payments recorded" />
        ) : (
          <Table head={["Date", "Amount", "Type", "Period", "Status", "Notes", ""]}>
            {data.map((p) => (
              <tr key={p.id}>
                <Td>{day(p.paid_on)}</Td>
                <Td>{money(p.amount_cents)}</Td>
                <Td>{label(p.payment_type)}</Td>
                <Td>{p.period_start ? `${day(p.period_start)} – ${day(p.period_end)}` : "—"}</Td>
                <Td>
                  <Badge
                    tone={
                      p.status === "received" ? "green" : p.status === "pending" ? "amber" : "red"
                    }
                  >
                    {label(p.status)}
                  </Badge>
                </Td>
                <Td className="max-w-xs text-xs">{p.notes ?? "—"}</Td>
                <Td>
                  <Select
                    aria-label="Change status"
                    value={p.status}
                    onChange={async (e) => {
                      await send(`/admin/api/payments/${p.id}`, "PATCH", {
                        status: e.target.value,
                      });
                      await reload();
                    }}
                  >
                    {["received", "pending", "failed", "refunded"].map((s) => (
                      <option key={s} value={s}>
                        {label(s)}
                      </option>
                    ))}
                  </Select>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
