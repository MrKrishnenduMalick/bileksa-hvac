"use client";

import Link from "next/link";
import { useState } from "react";
import { UrgencyBadge } from "@/components/badges";
import { Alert, Card, Empty, PageHeader, Select, Spinner, Table, Td } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, label, phone } from "@/lib/format";
import { LEAD_STATUSES, type Lead } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

export default function LeadsPage() {
  const [status, setStatus] = useState("");
  const { data, error, loading } = useLoad(
    () => api<Lead[]>(`/api/leads${status ? `?status=${status}` : ""}`),
    [status],
  );

  return (
    <>
      <PageHeader
        title="Leads"
        subtitle="Customers captured by your AI receptionist."
        action={
          <Select
            aria-label="Filter by status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="sm:w-48"
          >
            <option value="">All statuses</option>
            {LEAD_STATUSES.map((s) => (
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
          <Empty title="No leads yet">New leads appear here automatically after calls.</Empty>
        ) : (
          <Table head={["Name", "Phone", "Address", "HVAC problem", "Urgency", "Status", "Date"]}>
            {data.map((l) => (
              <tr key={l.id}>
                <Td>
                  <Link
                    href={`/app/lead?id=${l.id}`}
                    className="font-medium text-brand hover:underline"
                  >
                    {l.customer_name ?? "Unknown caller"}
                  </Link>
                </Td>
                <Td>
                  {phone(l.callback_number)}
                  {l.callback_number && !l.number_confirmed && (
                    <span className="block text-xs text-amber-700">Not confirmed</span>
                  )}
                </Td>
                <Td className="max-w-[12rem]">
                  {[l.address, l.zip_code].filter(Boolean).join(", ") || "—"}
                </Td>
                <Td className="max-w-xs">
                  {l.issue_summary ?? label(l.service_type)}
                  {l.equipment_type && (
                    <span className="block text-xs text-slate-500">
                      Equipment: {label(l.equipment_type)}
                    </span>
                  )}
                </Td>
                <Td>
                  <UrgencyBadge urgency={l.urgency} />
                </Td>
                <Td>{label(l.status)}</Td>
                <Td className="whitespace-nowrap">{dateTime(l.updated_at)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
