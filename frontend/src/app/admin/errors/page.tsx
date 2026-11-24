"use client";

import { Alert, Badge, Card, Empty, PageHeader, Spinner, Table, Td } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

type Row = {
  at: string;
  business: string | null;
  action: string;
  severity: string;
  target: string | null;
  detail: unknown;
};

export default function AdminErrorsPage() {
  const { data, error, loading } = useLoad(() => api<Row[]>("/admin/api/errors"));
  return (
    <>
      <PageHeader
        title="Errors"
        subtitle="Tool failures, provisioning and webhook problems, and refused security events."
      />
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No errors" />
        ) : (
          <Table head={["When", "Severity", "Event", "Business", "Target", "Detail"]}>
            {data.map((e, i) => (
              <tr key={i}>
                <Td>{dateTime(e.at)}</Td>
                <Td>
                  <Badge tone={e.severity === "error" ? "red" : "amber"}>{e.severity}</Badge>
                </Td>
                <Td>{label(e.action)}</Td>
                <Td>{e.business ?? "—"}</Td>
                <Td className="font-mono text-xs">{e.target ?? "—"}</Td>
                <Td className="max-w-sm font-mono text-xs">
                  {e.detail ? JSON.stringify(e.detail) : "—"}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
