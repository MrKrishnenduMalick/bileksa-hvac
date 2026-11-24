"use client";

import { Alert, Badge, Button, Card, Empty, Spinner } from "./ui";
import { api, send } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import type { Notification } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

/** Notifications feed; `base` is "/api" (owner) or "/admin/api" (BILEKSA). */
export function NotificationList({ base }: { base: string }) {
  const { data, error, loading, reload } = useLoad(
    () => api<Notification[]>(`${base}/notifications`),
    [base],
  );
  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error}</Alert>;
  const unread = data.filter((n) => !n.read).map((n) => n.id);
  return (
    <Card>
      {data.length === 0 ? (
        <Empty title="No notifications" />
      ) : (
        <>
          {unread.length > 0 && (
            <Button
              variant="secondary"
              className="mb-4"
              onClick={async () => {
                await send(`${base}/notifications/read`, "POST", { ids: unread });
                await reload();
              }}
            >
              Mark all as read
            </Button>
          )}
          <ul className="divide-y divide-slate-100">
            {data.map((n) => (
              <li key={n.id} className="py-3">
                <div className="flex flex-wrap items-center gap-2">
                  {!n.read && <Badge tone="blue">New</Badge>}
                  {n.kind === "emergency" && <Badge tone="red">Emergency</Badge>}
                  <span className="font-medium text-navy">{n.title}</span>
                  <span className="text-xs text-slate-500">{dateTime(n.created_at)}</span>
                </div>
                <p className="mt-1 whitespace-pre-line text-sm text-slate-700">{n.body}</p>
                <p className="mt-1 text-xs text-slate-400">Email: {label(n.email_status)}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
