"use client";

import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
  Stat,
  Table,
  Td,
} from "@/components/ui";
import { api, send } from "@/lib/api";
import type { ClientRow } from "@/lib/admin-types";
import { day, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

type Row = {
  business_id: string;
  name: string;
  usage_minutes: number;
  revenue_cents: number;
  vapi_cost_cents: number;
  telephony_cost_cents: number;
  fixed_allocation_cents: number;
  other_expenses_cents: number;
  total_cost_cents: number;
  gross_profit_cents: number;
  vapi_reported_cost_cents: number;
};
type Report = {
  month: string;
  assumptions: Record<string, number | string>;
  rows: Row[];
  unassigned_expenses_cents: number;
  totals: Omit<Row, "business_id" | "name">;
};
type Settings = {
  vapi_cost_per_minute: number;
  telephony_cost_per_minute: number;
  fixed_monthly_per_client: number;
  approaching_limit_percent: number;
  admin_notification_email: string | null;
  email_configured: boolean;
};
type Expense = {
  id: string;
  business_id: string | null;
  incurred_on: string;
  category: string;
  amount_cents: number;
  note: string | null;
};

const thisMonth = () => new Date().toISOString().slice(0, 7);

function SettingsForm({ s, onSaved }: { s: Settings; onSaved: () => Promise<void> }) {
  const [v, setV] = useState({
    vapi: String(s.vapi_cost_per_minute),
    tel: String(s.telephony_cost_per_minute),
    fixed: String(s.fixed_monthly_per_client),
    pct: String(s.approaching_limit_percent),
    email: s.admin_notification_email ?? "",
  });
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  return (
    <form
      className="grid gap-4 sm:grid-cols-5"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await send("/admin/api/settings", "PUT", {
            vapi_cost_per_minute: Number(v.vapi),
            telephony_cost_per_minute: Number(v.tel),
            fixed_monthly_per_client: Number(v.fixed),
            approaching_limit_percent: Number(v.pct),
            admin_notification_email: v.email || null,
          });
          setMsg({ tone: "green", text: "Saved." });
          await onSaved();
        } catch (err) {
          setMsg({ tone: "red", text: err instanceof Error ? err.message : "Could not save" });
        }
      }}
    >
      <Field label="Vapi $/min">
        <Input
          type="number"
          step="0.0001"
          min="0"
          value={v.vapi}
          onChange={(e) => setV({ ...v, vapi: e.target.value })}
        />
      </Field>
      <Field label="Telephony $/min">
        <Input
          type="number"
          step="0.0001"
          min="0"
          value={v.tel}
          onChange={(e) => setV({ ...v, tel: e.target.value })}
        />
      </Field>
      <Field label="Fixed $/client/month">
        <Input
          type="number"
          step="0.01"
          min="0"
          value={v.fixed}
          onChange={(e) => setV({ ...v, fixed: e.target.value })}
        />
      </Field>
      <Field label="Alert at % of limit">
        <Input
          type="number"
          min="1"
          max="99"
          value={v.pct}
          onChange={(e) => setV({ ...v, pct: e.target.value })}
        />
      </Field>
      <Field label="BILEKSA alert email">
        <Input
          type="email"
          value={v.email}
          onChange={(e) => setV({ ...v, email: e.target.value })}
        />
      </Field>
      <div className="space-y-2 sm:col-span-5">
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        {!s.email_configured && (
          <Alert tone="amber">
            Email delivery is not configured (SMTP_* settings); notifications show in the dashboards
            only.
          </Alert>
        )}
        <Button type="submit">Save assumptions</Button>
      </div>
    </form>
  );
}

export default function CostsPage() {
  const [month, setMonth] = useState(thisMonth());
  const report = useLoad(() => api<Report>(`/admin/api/costs?month=${month}`), [month]);
  const settings = useLoad(() => api<Settings>("/admin/api/settings"));
  const expenses = useLoad(() => api<Expense[]>(`/admin/api/expenses?month=${month}`), [month]);
  const clients = useLoad(() => api<ClientRow[]>("/admin/api/clients"));
  const [ex, setEx] = useState({
    business_id: "",
    incurred_on: `${thisMonth()}-01`,
    category: "",
    amount: "",
    note: "",
  });
  const [exMsg, setExMsg] = useState<string | null>(null);
  const reloadAll = async () => {
    await report.reload();
    await expenses.reload();
  };
  const t = report.data?.totals;

  return (
    <>
      <PageHeader
        title="Costs & profit"
        subtitle="Internal only. Estimated cost = fixed allocation + usage minutes × (Vapi + telephony per minute) + other expenses."
        action={
          <Input
            type="month"
            aria-label="Month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="sm:w-44"
          />
        }
      />
      {report.loading ? (
        <Spinner />
      ) : report.error || !report.data || !t ? (
        <Alert>{report.error}</Alert>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Revenue" value={money(t.revenue_cents)} />
            <Stat label="Total cost" value={money(t.total_cost_cents)} />
            <Stat label="Gross profit" value={money(t.gross_profit_cents)} />
            <Stat label="Usage minutes" value={t.usage_minutes} />
          </div>
          <Card className="mt-6">
            <Table
              head={[
                "Client",
                "Minutes",
                "Revenue",
                "Vapi (est.)",
                "Telephony",
                "Fixed",
                "Other",
                "Total cost",
                "Gross profit",
                "Vapi reported",
              ]}
            >
              {report.data.rows.map((r) => (
                <tr key={r.business_id}>
                  <Td>{r.name}</Td>
                  <Td>{r.usage_minutes}</Td>
                  <Td>{money(r.revenue_cents)}</Td>
                  <Td>{money(r.vapi_cost_cents)}</Td>
                  <Td>{money(r.telephony_cost_cents)}</Td>
                  <Td>{money(r.fixed_allocation_cents)}</Td>
                  <Td>{money(r.other_expenses_cents)}</Td>
                  <Td>{money(r.total_cost_cents)}</Td>
                  <Td className={r.gross_profit_cents < 0 ? "text-red-700" : ""}>
                    {money(r.gross_profit_cents)}
                  </Td>
                  <Td className="text-slate-500">{money(r.vapi_reported_cost_cents)}</Td>
                </tr>
              ))}
            </Table>
            {report.data.unassigned_expenses_cents > 0 && (
              <p className="mt-3 text-sm text-slate-600">
                Plus {money(report.data.unassigned_expenses_cents)} of expenses not tied to a client
                (included in the totals).
              </p>
            )}
          </Card>
        </>
      )}
      <Card className="mt-6">
        <h2 className="mb-3 font-semibold text-navy">Cost assumptions</h2>
        {settings.data ? (
          <SettingsForm
            s={settings.data}
            onSaved={async () => {
              await settings.reload();
              await report.reload();
            }}
          />
        ) : (
          <Spinner />
        )}
      </Card>
      <Card className="mt-6">
        <h2 className="mb-3 font-semibold text-navy">Other expenses ({month})</h2>
        <form
          className="mb-4 grid gap-3 sm:grid-cols-5"
          onSubmit={async (e) => {
            e.preventDefault();
            setExMsg(null);
            try {
              await send("/admin/api/expenses", "POST", {
                business_id: ex.business_id || null,
                incurred_on: ex.incurred_on,
                category: ex.category,
                amount_cents: Math.round(parseFloat(ex.amount) * 100),
                note: ex.note || null,
              });
              setEx({ ...ex, amount: "", note: "" });
              await reloadAll();
            } catch (err) {
              setExMsg(err instanceof Error ? err.message : "Could not add");
            }
          }}
        >
          <Field label="Client (optional)">
            <Select
              value={ex.business_id}
              onChange={(e) => setEx({ ...ex, business_id: e.target.value })}
            >
              <option value="">Platform-wide</option>
              {(clients.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Date">
            <Input
              type="date"
              required
              value={ex.incurred_on}
              onChange={(e) => setEx({ ...ex, incurred_on: e.target.value })}
            />
          </Field>
          <Field label="Category">
            <Input
              required
              minLength={2}
              maxLength={40}
              value={ex.category}
              onChange={(e) => setEx({ ...ex, category: e.target.value })}
            />
          </Field>
          <Field label="Amount ($)">
            <Input
              type="number"
              min="0.01"
              step="0.01"
              required
              value={ex.amount}
              onChange={(e) => setEx({ ...ex, amount: e.target.value })}
            />
          </Field>
          <Field label="Note">
            <Input
              maxLength={500}
              value={ex.note}
              onChange={(e) => setEx({ ...ex, note: e.target.value })}
            />
          </Field>
          <div className="space-y-2 sm:col-span-5">
            {exMsg && <Alert>{exMsg}</Alert>}
            <Button type="submit" variant="secondary">
              Add expense
            </Button>
          </div>
        </form>
        {expenses.data && expenses.data.length > 0 && (
          <Table head={["Date", "Category", "Client", "Amount", "Note", ""]}>
            {expenses.data.map((x) => (
              <tr key={x.id}>
                <Td>{day(x.incurred_on)}</Td>
                <Td>{x.category}</Td>
                <Td>{clients.data?.find((c) => c.id === x.business_id)?.name ?? "Platform"}</Td>
                <Td>{money(x.amount_cents)}</Td>
                <Td>{x.note ?? "—"}</Td>
                <Td>
                  <Button
                    variant="danger"
                    onClick={async () => {
                      await send(`/admin/api/expenses/${x.id}`, "DELETE");
                      await reloadAll();
                    }}
                  >
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
