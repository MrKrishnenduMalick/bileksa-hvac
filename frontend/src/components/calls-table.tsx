"use client";

import Link from "next/link";
import { OutcomeBadge, TransferBadge } from "./badges";
import { Badge, Table, Td } from "./ui";
import { dateTime, duration, label, phone } from "@/lib/format";
import type { CallRow } from "@/lib/types";

const ROUTING: Record<string, string> = {
  forwarded_limit: "Forwarded (minute limit reached)",
  forwarded_suspended: "Forwarded (service suspended)",
  unavailable: "Forwarded (receptionist unavailable)",
};

/** Call history in the columns the dashboard spec asks for. */
export function CallsTable({ calls, leadLinks = true }: { calls: CallRow[]; leadLinks?: boolean }) {
  return (
    <Table
      head={[
        "Caller",
        "Phone",
        "Date / time",
        "Duration",
        "Status",
        "Summary",
        "Lead outcome",
        "Emergency",
      ]}
    >
      {calls.map((c) => (
        <tr key={c.id}>
          <Td>
            {c.lead_id && leadLinks ? (
              <Link className="text-brand hover:underline" href={`/app/lead?id=${c.lead_id}`}>
                {c.caller_name ?? "View lead"}
              </Link>
            ) : (
              (c.caller_name ?? "—")
            )}
          </Td>
          <Td className="whitespace-nowrap">{phone(c.caller)}</Td>
          <Td className="whitespace-nowrap">{dateTime(c.started_at)}</Td>
          <Td>{duration(c.duration_seconds)}</Td>
          <Td>
            {ROUTING[c.routing] ? (
              <Badge tone="amber">{ROUTING[c.routing]}</Badge>
            ) : (
              <Badge tone={c.status === "completed" ? "green" : "amber"}>{label(c.status)}</Badge>
            )}
            {c.transfer_status !== "none" && (
              <div className="mt-1">
                <TransferBadge status={c.transfer_status} />
              </div>
            )}
          </Td>
          <Td className="max-w-xs text-xs text-slate-600">
            {c.summary ?? "—"}
            {c.numbers_to_check.length > 0 && (
              <p
                className="mt-1 text-amber-800"
                title="The receptionist said these amounts but no tool provided them. Please verify."
              >
                Check numbers: {c.numbers_to_check.join(", ")}
              </p>
            )}
          </Td>
          <Td>
            <OutcomeBadge outcome={c.outcome} />
          </Td>
          <Td>
            {c.urgent ? (
              <Badge tone="red">{label(c.emergency_type ?? "emergency")}</Badge>
            ) : (
              <span className="text-slate-400">—</span>
            )}
          </Td>
        </tr>
      ))}
    </Table>
  );
}
