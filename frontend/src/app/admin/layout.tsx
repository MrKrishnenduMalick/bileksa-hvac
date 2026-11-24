import { AppShell } from "@/components/app-shell";
import { MfaGate } from "@/components/mfa-gate";
import { SessionGate } from "@/components/session";

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <SessionGate need="admin">
      <MfaGate>
        <AppShell admin>{children}</AppShell>
      </MfaGate>
    </SessionGate>
  );
}
