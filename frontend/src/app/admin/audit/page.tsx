"use client";

import { useState } from "react";
import { Alert, Card, Empty, Input, PageHeader, Spinner, Table, Td } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

type Row = {
  at: string;
  business_id: string | null;
  actor: string;
  action: string;
  target: string | null;
  severity: string;
};

export default function AdminAuditPage() {
  const [action, setAction] = useState("");
  const { data, error, loading } = useLoad(
    () => api<Row[]>(`/admin/api/audit${action ? `?action=${encodeURIComponent(action)}` : ""}`),
    [action],
  );
  return (
    <>
      <PageHeader
        title="Audit log"
        action={
          <Input
            aria-label="Filter by action"
            placeholder="Filter by action, e.g. lead_updated"
            value={action}
            onChange={(e) => setAction(e.target.value.trim())}
            className="sm:w-72"
          />
        }
      />
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No entries" />
        ) : (
          <Table head={["When", "Actor", "Action", "Business", "Target", "Severity"]}>
            {data.map((r, i) => (
              <tr key={i}>
                <Td>{dateTime(r.at)}</Td>
                <Td className="font-mono text-xs">{r.actor}</Td>
                <Td>{label(r.action)}</Td>
                <Td className="font-mono text-xs">{r.business_id?.slice(0, 8) ?? "—"}</Td>
                <Td className="font-mono text-xs">{r.target ?? "—"}</Td>
                <Td>{r.severity}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
