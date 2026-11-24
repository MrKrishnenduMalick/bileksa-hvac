"use client";

import Link from "next/link";
import { ReceptionistBadge, ServiceStatusBadge, UsageBar } from "@/components/badges";
import { CallsTable } from "@/components/calls-table";
import { useSession } from "@/components/session";
import { Alert, Card, Empty, PageHeader, Spinner, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { day } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

export default function OverviewPage() {
  const { me } = useSession();
  const { data, error, loading } = useLoad(() => api<Overview>("/api/dashboard/overview"));

  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error ?? "Could not load your dashboard"}</Alert>;
  const m = data.metrics;
  const r = data.receptionist;
  const u = data.usage;

  return (
    <>
      <PageHeader
        title={me.business?.name ?? "Overview"}
        subtitle={`Current period since ${day(u.period_start)} · resets ${day(u.reset_date)}`}
      />
      {u.limit_reached && (
        <div className="mb-6">
          <Alert>
            You have used all {u.included_minutes} included minutes. New calls are being forwarded
            to your direct line without the AI receptionist.{" "}
            <Link href="/app/packages" className="font-medium underline">
              Request an upgrade
            </Link>
          </Alert>
        </div>
      )}
      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <p className="text-sm text-slate-500">AI receptionist status</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ReceptionistBadge
              state={
                ["limit_reached", "suspended"].includes(r.service_status)
                  ? "failed"
                  : r.provisioning_state
              }
              label={r.status_label}
            />
            <ServiceStatusBadge status={r.service_status} />
          </div>
          <p className="mt-2 text-sm text-slate-600">
            Phone connection: {r.phone_state.replace("_", " ")}
          </p>
        </Card>
        <Card>
          <div className="flex items-baseline justify-between">
            <p className="text-sm text-slate-500">
              Current package:{" "}
              <span className="font-medium text-navy">{u.package?.name ?? "—"}</span>
            </p>
            <Link href="/app/usage" className="text-sm text-brand hover:underline">
              Usage details
            </Link>
          </div>
          <p className="mt-2 text-2xl font-semibold text-navy">
            {u.used_minutes}{" "}
            <span className="text-base font-normal text-slate-500">
              of {u.included_minutes} minutes used
            </span>
          </p>
          <div className="mt-3">
            <UsageBar percent={u.usage_percent} />
          </div>
          <p className="mt-2 text-sm text-slate-600">{u.remaining_minutes} minutes remaining</p>
        </Card>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Total calls" value={m.total_calls} />
        <Stat label="Leads generated" value={m.leads_captured} />
        <Stat label="Callback requests" value={m.callback_requests} />
        <Stat label="Appointment requests" value={m.appointment_requests} />
        <Stat label="Emergency calls" value={m.urgent_calls} />
        <Stat label="Human transfers" value={m.human_transfers} />
        <Stat label="Minutes used" value={m.minutes_used} hint={`${m.included_minutes} included`} />
        <Stat label="Minutes remaining" value={m.remaining_minutes} />
      </div>
      <Card className="mt-6">
        <h2 className="mb-3 font-semibold text-navy">Recent calls</h2>
        {data.recent_activity.length === 0 ? (
          <Empty title="No calls yet">
            Calls appear here as soon as your receptionist answers them.
          </Empty>
        ) : (
          <CallsTable calls={data.recent_activity} />
        )}
      </Card>
    </>
  );
}
