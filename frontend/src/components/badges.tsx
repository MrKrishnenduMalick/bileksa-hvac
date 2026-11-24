import { label } from "@/lib/format";
import { Badge } from "./ui";

const OUTCOME_TONE: Record<string, "green" | "blue" | "amber" | "red" | "gray"> = {
  lead_captured: "green",
  callback_requested: "blue",
  appointment_requested: "blue",
  forwarded: "amber",
  transfer: "blue",
  answered: "green",
  no_conversation: "gray",
  failed: "red",
  in_progress: "amber",
};

export function OutcomeBadge({ outcome }: { outcome: string }) {
  return <Badge tone={OUTCOME_TONE[outcome] ?? "gray"}>{label(outcome)}</Badge>;
}

export function TransferBadge({ status }: { status: string }) {
  if (status === "none") return <span className="text-slate-400">—</span>;
  const text = status === "attempted" ? "Attempted, outcome unconfirmed" : label(status);
  const tone =
    status === "connected"
      ? "green"
      : status === "attempted"
        ? "amber"
        : status === "not_allowed"
          ? "gray"
          : "red";
  return <Badge tone={tone}>{text}</Badge>;
}

export function UrgencyBadge({ urgency }: { urgency: string }) {
  const tone = urgency === "emergency" ? "red" : urgency === "urgent" ? "amber" : "gray";
  return <Badge tone={tone}>{label(urgency)}</Badge>;
}

export function ReceptionistBadge({ state, label: text }: { state: string; label: string }) {
  const tone =
    state === "active"
      ? "green"
      : state === "verified"
        ? "blue"
        : state === "failed"
          ? "red"
          : "amber";
  return <Badge tone={tone}>{text}</Badge>;
}

const SERVICE_TONE: Record<string, "green" | "blue" | "amber" | "red" | "gray"> = {
  active: "green",
  onboarding: "blue",
  limit_reached: "red",
  suspended: "red",
};

export function ServiceStatusBadge({ status }: { status: string }) {
  const text = status === "limit_reached" ? "LIMIT_REACHED" : label(status);
  return <Badge tone={SERVICE_TONE[status] ?? "gray"}>{text}</Badge>;
}

export function UsageBar({ percent }: { percent: number }) {
  const pct = Math.min(100, Math.max(0, percent));
  const color = pct >= 100 ? "bg-red-600" : pct >= 80 ? "bg-amber-500" : "bg-brand";
  return (
    <div
      className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200"
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Minutes used"
    >
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
