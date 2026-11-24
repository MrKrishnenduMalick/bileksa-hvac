"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Card, Empty, Input, PageHeader, Select, Spinner, Table, Td } from "@/components/ui";
import { api, send } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import type { UpgradeRequest } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

const STATUSES = ["open", "contacted", "payment_verified", "declined"];

export default function UpgradesPage() {
  const [filter, setFilter] = useState("");
  const { data, error, loading, reload } = useLoad(
    () => api<UpgradeRequest[]>(`/admin/api/upgrade-requests${filter ? `?status=${filter}` : ""}`),
    [filter],
  );
  return (
    <>
      <PageHeader
        title="Upgrade requests"
        subtitle="Contact the client, verify payment, then activate the package from the client's Overview tab (password confirmation)."
        action={
          <Select
            aria-label="Filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="sm:w-48"
          >
            <option value="">All</option>
            {[...STATUSES, "completed"].map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </Select>
        }
      />
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No upgrade requests" />
        ) : (
          <Table head={["Requested", "Client", "Package", "Message", "Status", "Notes"]}>
            {data.map((r) => (
              <tr key={r.id}>
                <Td>{dateTime(r.created_at)}</Td>
                <Td>
                  <Link
                    className="text-brand hover:underline"
                    href={`/admin/client?id=${r.business_id}`}
                  >
                    {r.business_name}
                  </Link>
                </Td>
                <Td>{r.requested_package?.name ?? "—"}</Td>
                <Td className="max-w-xs text-sm">{r.message ?? "—"}</Td>
                <Td>
                  {r.status === "completed" ? (
                    label(r.status)
                  ) : (
                    <Select
                      aria-label="Status"
                      value={r.status}
                      onChange={async (e) => {
                        await send(`/admin/api/upgrade-requests/${r.id}`, "PATCH", {
                          status: e.target.value,
                        });
                        await reload();
                      }}
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {label(s)}
                        </option>
                      ))}
                    </Select>
                  )}
                </Td>
                <Td>
                  <Input
                    aria-label="Admin notes"
                    defaultValue={r.admin_notes ?? ""}
                    maxLength={1000}
                    onBlur={async (e) => {
                      if (e.target.value !== (r.admin_notes ?? ""))
                        await send(`/admin/api/upgrade-requests/${r.id}`, "PATCH", {
                          admin_notes: e.target.value,
                        });
                    }}
                  />
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
