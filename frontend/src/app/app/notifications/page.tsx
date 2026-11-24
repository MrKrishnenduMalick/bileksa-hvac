"use client";

import { NotificationList } from "@/components/notification-list";
import { PageHeader } from "@/components/ui";

export default function NotificationsPage() {
  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Call summaries, emergencies and account updates. They are also emailed when email is set up."
      />
      <NotificationList base="/api" />
    </>
  );
}
