"use client";

import { useState } from "react";
import { ServiceStatusBadge, UsageBar } from "../badges";
import { Alert, Button, Card, Field, Input, Select } from "../ui";
import { PasswordDialog } from "./password-dialog";
import { api, send } from "@/lib/api";
import { day, money } from "@/lib/format";
import type { Package, UpgradeRequest, Usage } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

type Pending = { summary: string; body: Record<string, unknown> };

/** Usage, package and service status, with every change confirmed by password. */
export function ServicePanel({
  clientId,
  usage,
  onChanged,
}: {
  clientId: string;
  usage: Usage;
  onChanged: () => Promise<void>;
}) {
  const pkgs = useLoad(() => api<Package[]>("/admin/api/packages"));
  const requests = useLoad(() => api<UpgradeRequest[]>("/admin/api/upgrade-requests"), [clientId]);
  const openRequest = requests.data?.find(
    (r) =>
      r.business_id === clientId && ["open", "contacted", "payment_verified"].includes(r.status),
  );
  const [pkg, setPkg] = useState("");
  const [minutes, setMinutes] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const active = (pkgs.data ?? []).filter((p) => p.active);
  const nameOf = (id: string) => active.find((p) => p.id === id)?.name ?? "package";

  function ask(summary: string, body: Record<string, unknown>) {
    setMsg(null);
    setPending({ summary, body });
  }

  async function confirm(password: string) {
    if (!pending) return;
    await send(`/admin/api/clients/${clientId}/service-action`, "POST", {
      ...pending.body,
      password,
      reason: reason || null,
    });
    setPending(null);
    setMsg("Change applied and logged. The client has been notified.");
    setReason("");
    await requests.reload();
    await onChanged();
  }

  const s = usage.service_status;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-navy">Package, minutes and service</h2>
        <ServiceStatusBadge status={s} />
      </div>
      <p className="mt-3 text-sm text-slate-700">
        {usage.package?.name ?? "No package"} · {usage.used_minutes} of {usage.included_minutes}{" "}
        minutes used · {usage.remaining_minutes} remaining · resets {day(usage.reset_date)}
        {usage.renewal_overdue && <span className="text-amber-700"> (renewal overdue)</span>}
      </p>
      <div className="mt-2">
        <UsageBar percent={usage.usage_percent} />
      </div>
      {msg && (
        <div className="mt-4">
          <Alert tone="green">{msg}</Alert>
        </div>
      )}
      {openRequest && (
        <div className="mt-4">
          <Alert tone="blue">
            Upgrade request ({openRequest.status.replace("_", " ")}):{" "}
            {openRequest.requested_package?.name ?? "no package chosen"}
            {openRequest.message ? ` — “${openRequest.message}”` : ""}
            {openRequest.requested_package && (
              <Button
                className="ml-3"
                onClick={() =>
                  ask(
                    `Activate ${openRequest.requested_package?.name} (${openRequest.requested_package?.included_minutes} minutes) and complete the upgrade request.\nOnly do this after payment has been verified.`,
                    {
                      action: "assign_package",
                      package_id: openRequest.requested_package?.id,
                      upgrade_request_id: openRequest.id,
                    },
                  )
                }
              >
                Activate requested package
              </Button>
            )}
          </Alert>
        </div>
      )}
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (pkg)
              ask(
                `Assign the ${nameOf(pkg)} package. The minute limit becomes the package's included minutes.`,
                { action: "assign_package", package_id: pkg },
              );
          }}
        >
          <Field label="Assign / upgrade / downgrade package">
            <Select value={pkg} onChange={(e) => setPkg(e.target.value)} required>
              <option value="">Choose a package…</option>
              {active.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {money(p.price_cents)}/mo · {p.included_minutes} min
                </option>
              ))}
            </Select>
          </Field>
          <Button type="submit" variant="secondary">
            Assign package
          </Button>
        </form>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            ask(`Change the minute limit from ${usage.included_minutes} to ${minutes} minutes.`, {
              action: "change_limit",
              included_minutes: Number(minutes),
            });
          }}
        >
          <Field label="Change minute limit">
            <Input
              type="number"
              min="0"
              required
              value={minutes}
              onChange={(e) => setMinutes(e.target.value)}
            />
          </Field>
          <Button type="submit" variant="secondary">
            Change limit
          </Button>
        </form>
      </div>
      <div className="mt-4">
        <Field label="Reason (optional, saved in the audit log)">
          <Input maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {s === "onboarding" && (
          <Button
            onClick={() =>
              ask("Activate this client. A new usage period starts now.", { action: "activate" })
            }
          >
            Activate client
          </Button>
        )}
        <Button
          variant="secondary"
          onClick={() =>
            ask(
              "Renew the usage period: a new one-month period starts now and used minutes reset to 0.",
              { action: "renew_period" },
            )
          }
        >
          Renew period
        </Button>
        <Button
          variant="secondary"
          onClick={() =>
            ask("Reset usage: used minutes reset to 0 from now; the reset date stays the same.", {
              action: "reset_usage",
            })
          }
        >
          Reset usage
        </Button>
        {s === "suspended" ? (
          <Button
            onClick={() =>
              ask("Restore service. The AI answers calls again if minutes remain.", {
                action: "restore",
              })
            }
          >
            Restore service
          </Button>
        ) : (
          <Button
            variant="danger"
            onClick={() =>
              ask(
                "Suspend service. New calls are forwarded to the client's direct line without the AI.",
                { action: "suspend" },
              )
            }
          >
            Suspend service
          </Button>
        )}
      </div>
      {pending && (
        <PasswordDialog
          summary={pending.summary}
          onConfirm={confirm}
          onCancel={() => setPending(null)}
        />
      )}
    </Card>
  );
}
