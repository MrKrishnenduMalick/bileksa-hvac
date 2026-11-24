"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, PageHeader, Spinner, Table, Td } from "@/components/ui";
import { api, send } from "@/lib/api";
import { useLoad } from "@/lib/use-load";

type Status = {
  template_version: number;
  tools: { name: string; vapi_tool_id: string | null }[];
  missing: string[];
};

export default function VapiPage() {
  const { data, error, loading, reload } = useLoad(() => api<Status>("/admin/api/vapi/tools"));
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <PageHeader
        title="Vapi tools"
        subtitle="One standard tool set, attached directly to every client's Vapi assistant. Vapi decides when to call a tool; the backend only executes it."
        action={
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setMsg(null);
              try {
                await send("/admin/api/vapi/tools/sync", "POST");
                setMsg({
                  tone: "green",
                  text: "Tools synced. Assistants are re-synced by the next sweep.",
                });
                await reload();
              } catch (err) {
                setMsg({ tone: "red", text: err instanceof Error ? err.message : "Sync failed" });
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Syncing…" : "Sync tools to Vapi"}
          </Button>
        }
      />
      {msg && (
        <div className="mb-4">
          <Alert tone={msg.tone}>{msg.text}</Alert>
        </div>
      )}
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : (
          <>
            <p className="mb-3 text-sm text-slate-600">
              Master template version {data.template_version}
            </p>
            <Table head={["Tool", "Vapi tool ID", "Status"]}>
              {data.tools.map((t) => (
                <tr key={t.name}>
                  <Td className="font-mono text-sm">{t.name}</Td>
                  <Td className="font-mono text-xs">{t.vapi_tool_id ?? "—"}</Td>
                  <Td>
                    {t.vapi_tool_id ? (
                      <Badge tone="green">In Vapi</Badge>
                    ) : (
                      <Badge tone="red">Missing</Badge>
                    )}
                  </Td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </Card>
    </>
  );
}
