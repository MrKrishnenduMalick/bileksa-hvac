"use client";

import Link from "next/link";
import { ServiceStatusBadge, UsageBar } from "@/components/badges";
import { Alert, Card, Empty, PageHeader, Spinner, Table, Td } from "@/components/ui";
import { api } from "@/lib/api";
import type { ClientRow } from "@/lib/admin-types";
import { day } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function UsageAdminPage() {
  const { data, error, loading } = useLoad(() => api<ClientRow[]>("/admin/api/usage"));
  const sorted = [...(data ?? [])].sort((a, b) => b.usage_percent - a.usage_percent);
  return (
    <>
      <PageHeader
        title="Usage & limits"
        subtitle="Clients sorted by how much of their limit they have used. Change limits or renew periods from the client page."
      />
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : sorted.length === 0 ? (
          <Empty title="No clients" />
        ) : (
          <Table head={["Client", "Status", "Package", "Used", "Remaining", "Usage", "Reset date"]}>
            {sorted.map((c) => (
              <tr key={c.id}>
                <Td>
                  <Link className="text-brand hover:underline" href={`/admin/client?id=${c.id}`}>
                    {c.name}
                  </Link>
                </Td>
                <Td>
                  <ServiceStatusBadge status={c.service_status} />
                  {c.approaching_limit && (
                    <span className="block text-xs text-amber-700">Approaching limit</span>
                  )}
                </Td>
                <Td>{c.package?.name ?? "—"}</Td>
                <Td>
                  {c.used_minutes} / {c.included_minutes}
                </Td>
                <Td>{c.remaining_minutes}</Td>
                <Td className="min-w-[8rem]">
                  <UsageBar percent={c.usage_percent} />
                  <span className="text-xs text-slate-600">{c.usage_percent}%</span>
                </Td>
                <Td>
                  {day(c.reset_date)}
                  {c.renewal_overdue && (
                    <span className="block text-xs text-amber-700">Overdue</span>
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
