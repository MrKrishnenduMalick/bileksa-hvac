"use client";

import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Field,
  Input,
  PageHeader,
  Spinner,
} from "@/components/ui";
import { api, send } from "@/lib/api";
import { money } from "@/lib/format";
import type { Package } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

function PackageForm({ pkg, onSaved }: { pkg: Package; onSaved: () => Promise<void> }) {
  const [v, setV] = useState({
    name: pkg.name,
    price: String(pkg.price_cents / 100),
    minutes: String(pkg.included_minutes),
    features: pkg.features.join("\n"),
    active: pkg.active ?? true,
  });
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  return (
    <Card>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setMsg(null);
          try {
            await send(`/admin/api/packages/${pkg.id}`, "PATCH", {
              name: v.name,
              price_cents: Math.round(parseFloat(v.price) * 100),
              included_minutes: Number(v.minutes),
              features: v.features
                .split("\n")
                .map((f) => f.trim())
                .filter(Boolean),
              active: v.active,
            });
            setMsg({ tone: "green", text: "Saved." });
            await onSaved();
          } catch (err) {
            setMsg({ tone: "red", text: err instanceof Error ? err.message : "Could not save" });
          }
        }}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-navy">{pkg.name}</h2>
          {pkg.active ? <Badge tone="green">Active</Badge> : <Badge>Inactive</Badge>}
        </div>
        <p className="text-sm text-slate-600">
          {money(pkg.price_cents)}/month · {pkg.included_minutes} minutes
        </p>
        <Field label="Name">
          <Input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Price ($/month)">
            <Input
              type="number"
              min="0"
              step="0.01"
              value={v.price}
              onChange={(e) => setV({ ...v, price: e.target.value })}
            />
          </Field>
          <Field label="Included minutes">
            <Input
              type="number"
              min="0"
              value={v.minutes}
              onChange={(e) => setV({ ...v, minutes: e.target.value })}
            />
          </Field>
        </div>
        <Field label="Features (one per line)">
          <textarea
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
            rows={6}
            value={v.features}
            onChange={(e) => setV({ ...v, features: e.target.value })}
          />
        </Field>
        <Checkbox
          label="Available to clients"
          checked={v.active}
          onChange={(e) => setV({ ...v, active: e.target.checked })}
        />
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <Button type="submit">Save package</Button>
      </form>
    </Card>
  );
}

export default function PackagesAdminPage() {
  const { data, error, loading, reload } = useLoad(() => api<Package[]>("/admin/api/packages"));
  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error}</Alert>;
  return (
    <>
      <PageHeader
        title="Packages"
        subtitle="Changing a package does not change existing clients' limits: re-assign the package on a client (password confirmation) to apply it."
      />
      <div className="grid gap-6 lg:grid-cols-3">
        {data.map((p) => (
          <PackageForm key={p.id} pkg={p} onSaved={reload} />
        ))}
      </div>
    </>
  );
}
