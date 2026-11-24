"use client";

import Link from "next/link";
import { ServiceStatusBadge, UsageBar } from "@/components/badges";
import { Alert, Card, PageHeader, Spinner, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { day } from "@/lib/format";
import type { Usage } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

export default function UsagePage() {
  const { data: u, error, loading } = useLoad(() => api<Usage>("/api/usage"));
  if (loading) return <Spinner />;
  if (error || !u) return <Alert>{error ?? "Could not load usage"}</Alert>;
  const limitText = u.limit_reached
    ? "Limit reached: new calls are forwarded to your direct line without the AI."
    : u.usage_percent >= 80
      ? "Approaching your limit."
      : "Within your limit.";
  return (
    <>
      <PageHeader
        title="Usage"
        subtitle="Included minutes are a hard limit. There are no automatic overage charges."
      />
      <Card className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-medium text-navy">
            {u.package?.name ?? "No package"} · {u.included_minutes} minutes per period
          </p>
          <ServiceStatusBadge status={u.service_status} />
        </div>
        <div className="mt-4">
          <UsageBar percent={u.usage_percent} />
        </div>
        <p className="mt-2 text-sm text-slate-600">
          {u.usage_percent}% used · {limitText}
        </p>
        {u.renewal_overdue && (
          <div className="mt-3">
            <Alert tone="amber">
              Your period reset date has passed and has not been renewed yet. Usage continues to
              count against the current limit until BILEKSA renews it.
            </Alert>
          </div>
        )}
      </Card>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Stat label="Included minutes" value={u.included_minutes} />
        <Stat label="Used minutes" value={u.used_minutes} />
        <Stat label="Remaining minutes" value={u.remaining_minutes} />
        <Stat label="Usage" value={`${u.usage_percent}%`} />
        <Stat label="Period started" value={day(u.period_start)} />
        <Stat label="Reset date" value={day(u.reset_date)} />
      </div>
      <p className="mt-6 text-sm text-slate-600">
        Need more minutes?{" "}
        <Link className="font-medium text-brand hover:underline" href="/app/packages">
          Request an upgrade
        </Link>
        . Only BILEKSA can change packages or limits.
      </p>
    </>
  );
}
