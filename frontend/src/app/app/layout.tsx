import { AppShell } from "@/components/app-shell";
import { SessionGate } from "@/components/session";

export default function CustomerLayout({ children }: LayoutProps<"/app">) {
  return (
    <SessionGate need="business">
      <AppShell>{children}</AppShell>
    </SessionGate>
  );
}
