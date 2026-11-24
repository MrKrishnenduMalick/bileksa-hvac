"use client";

import Link from "next/link";
import { UrgencyBadge } from "@/components/badges";
import { Alert, Badge, Button, Card, Empty, PageHeader, Spinner, Table, Td } from "@/components/ui";
import { api, send } from "@/lib/api";
import { dateTime, label, phone } from "@/lib/format";
import type { Lead } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

export default function CallbacksPage() {
  const { data, error, loading, reload } = useLoad(() => api<Lead[]>("/api/leads?callbacks=true"));
  const appts = useLoad(() => api<Lead[]>("/api/leads?appointments=true"));

  async function done(id: string) {
    await send(`/api/leads/${id}`, "PATCH", { callback_status: "done" });
    await reload();
  }

  async function setAppointment(id: string, status: string) {
    await send(`/api/leads/${id}`, "PATCH", { appointment_status: status });
    await appts.reload();
  }

  return (
    <>
      <PageHeader
        title="Callbacks & appointments"
        subtitle="Callers who asked your team to call them back or requested an appointment. The receptionist never promises a time and never confirms a booking."
      />
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No callback requests" />
        ) : (
          <Table
            head={[
              "Customer",
              "Number",
              "Preferred time",
              "Reason",
              "Urgency",
              "Requested",
              "Status",
              "",
            ]}
          >
            {data.map((l) => (
              <tr key={l.id}>
                <Td>
                  <Link className="text-brand hover:underline" href={`/app/lead?id=${l.id}`}>
                    {l.customer_name ?? "Unknown caller"}
                  </Link>
                </Td>
                <Td>{phone(l.callback_number)}</Td>
                <Td>{l.callback_preferred_time ?? "—"}</Td>
                <Td className="max-w-xs">{l.callback_reason ?? l.issue_summary ?? "—"}</Td>
                <Td>
                  <UrgencyBadge urgency={l.urgency} />
                </Td>
                <Td>{dateTime(l.created_at)}</Td>
                <Td>
                  <Badge tone={l.callback_status === "requested" ? "amber" : "green"}>
                    {l.callback_status === "requested" ? "Waiting" : "Done"}
                  </Badge>
                </Td>
                <Td>
                  {l.callback_status === "requested" && (
                    <Button variant="secondary" onClick={() => done(l.id)}>
                      Mark done
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <Card className="mt-6">
        <h2 className="mb-1 font-semibold text-navy">Appointment requests</h2>
        <p className="mb-4 text-sm text-slate-600">
          These are requests, not bookings. Confirm the time with the customer, then mark it
          confirmed.
        </p>
        {appts.loading ? (
          <Spinner />
        ) : appts.error || !appts.data ? (
          <Alert>{appts.error}</Alert>
        ) : appts.data.length === 0 ? (
          <Empty title="No appointment requests" />
        ) : (
          <Table head={["Customer", "Phone", "Preferred time", "Service", "Urgency", "Status", ""]}>
            {appts.data.map((l) => (
              <tr key={l.id}>
                <Td>
                  <Link className="text-brand hover:underline" href={`/app/lead?id=${l.id}`}>
                    {l.customer_name ?? "Unknown caller"}
                  </Link>
                </Td>
                <Td>{phone(l.callback_number)}</Td>
                <Td>{l.preferred_appointment ?? "—"}</Td>
                <Td className="max-w-xs">
                  {l.service_type ? label(l.service_type) : (l.issue_summary ?? "—")}
                </Td>
                <Td>
                  <UrgencyBadge urgency={l.urgency} />
                </Td>
                <Td>
                  <Badge
                    tone={
                      l.appointment_status === "requested"
                        ? "amber"
                        : l.appointment_status === "cancelled"
                          ? "gray"
                          : "green"
                    }
                  >
                    {label(l.appointment_status)}
                  </Badge>
                </Td>
                <Td className="whitespace-nowrap">
                  {l.appointment_status === "requested" && (
                    <>
                      <Button variant="secondary" onClick={() => setAppointment(l.id, "confirmed")}>
                        Confirmed
                      </Button>{" "}
                      <Button variant="danger" onClick={() => setAppointment(l.id, "cancelled")}>
                        Cancel
                      </Button>
                    </>
                  )}
                  {l.appointment_status === "confirmed" && (
                    <Button variant="secondary" onClick={() => setAppointment(l.id, "done")}>
                      Mark done
                    </Button>
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
