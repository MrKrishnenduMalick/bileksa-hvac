"use client";

import { NotificationList } from "@/components/notification-list";
import { PageHeader } from "@/components/ui";

export default function AdminNotificationsPage() {
  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Upgrade requests, limits, tool failures, call failures and Vapi incidents."
      />
      <NotificationList base="/admin/api" />
    </>
  );
}
