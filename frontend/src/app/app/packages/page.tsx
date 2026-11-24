"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, Field, PageHeader, Spinner, Table, Td } from "@/components/ui";
import { api, send } from "@/lib/api";
import { dateTime, label, money } from "@/lib/format";
import type { Package, UpgradeRequest } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

type Packages = {
  current_package_id: string | null;
  included_minutes: number;
  packages: Package[];
  how_upgrades_work: string;
};

export default function PackagesPage() {
  const pkgs = useLoad(() => api<Packages>("/api/packages"));
  const requests = useLoad(() => api<UpgradeRequest[]>("/api/upgrade-requests"));
  const [choice, setChoice] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const open = requests.data?.find((r) =>
    ["open", "contacted", "payment_verified"].includes(r.status),
  );

  async function request(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      await send("/api/upgrade-requests", "POST", { package_id: choice, message: message || null });
      setMsg({ tone: "green", text: "Request sent. BILEKSA will contact you to arrange payment." });
      setMessage("");
      await requests.reload();
    } catch (err) {
      setMsg({ tone: "red", text: err instanceof Error ? err.message : "Could not send" });
    }
  }

  if (pkgs.loading) return <Spinner />;
  if (pkgs.error || !pkgs.data) return <Alert>{pkgs.error}</Alert>;
  const names = Object.fromEntries(pkgs.data.packages.map((p) => [p.id, p.name]));

  return (
    <>
      <PageHeader title="Packages" subtitle={pkgs.data.how_upgrades_work} />
      <div className="grid gap-4 md:grid-cols-3">
        {pkgs.data.packages.map((p) => {
          const current = p.id === pkgs.data?.current_package_id;
          return (
            <Card key={p.id} className={current ? "ring-2 ring-brand" : ""}>
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-navy">{p.name}</h2>
                {current && <Badge tone="green">Current</Badge>}
              </div>
              <p className="mt-1 text-2xl font-semibold">
                {money(p.price_cents)}
                <span className="text-sm font-normal text-slate-500">/month</span>
              </p>
              <p className="text-sm text-slate-600">{p.included_minutes} minutes included</p>
              <ul className="mt-3 space-y-1 text-sm text-slate-700">
                {p.features.map((f) => (
                  <li key={f}>✓ {f}</li>
                ))}
              </ul>
              {!current && !open && (
                <Button
                  variant={choice === p.id ? "primary" : "secondary"}
                  className="mt-4 w-full"
                  onClick={() => setChoice(p.id)}
                >
                  {choice === p.id ? "Selected" : "Choose"}
                </Button>
              )}
            </Card>
          );
        })}
      </div>
      <Card className="mt-6">
        <h2 className="mb-3 font-semibold text-navy">Request an upgrade</h2>
        {msg && (
          <div className="mb-3">
            <Alert tone={msg.tone}>{msg.text}</Alert>
          </div>
        )}
        {open ? (
          <Alert tone="blue">
            Your request ({label(open.status)}) is with BILEKSA. We&apos;ll contact you; the new
            package is activated once payment is confirmed.
          </Alert>
        ) : (
          <form onSubmit={request} className="space-y-3">
            <p className="text-sm text-slate-600">
              {choice
                ? `Requesting: ${names[choice]}`
                : "Choose a package above, or just send a message."}
            </p>
            <Field label="Message (optional)">
              <textarea
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
                rows={3}
                maxLength={1000}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
            </Field>
            <Button type="submit">Request upgrade</Button>
          </form>
        )}
      </Card>
      {requests.data && requests.data.length > 0 && (
        <Card className="mt-6">
          <h2 className="mb-3 font-semibold text-navy">Your requests</h2>
          <Table head={["Requested", "Package", "Status"]}>
            {requests.data.map((r) => (
              <tr key={r.id}>
                <Td>{dateTime(r.created_at)}</Td>
                <Td>{r.requested_package_id ? (names[r.requested_package_id] ?? "—") : "—"}</Td>
                <Td>{label(r.status)}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </>
  );
}
