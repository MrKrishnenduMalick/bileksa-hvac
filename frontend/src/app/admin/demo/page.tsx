"use client";

import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Field,
  Input,
  PageHeader,
  Spinner,
  Stat,
} from "@/components/ui";
import { api, send } from "@/lib/api";
import { DEMO, type VoiceStatus } from "@/lib/demo";
import { dateTime } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const usd = (n: number) => `$${n.toFixed(2)}`;

export default function DemoControls() {
  const { data, error, loading, reload } = useLoad(
    () => (DEMO ? api<VoiceStatus>("/admin/api/demo/voice") : Promise.resolve(null)),
    [],
  );
  const [budget, setBudget] = useState<string>("");
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ tone: "green", text: ok });
      await reload();
    } catch (e) {
      setMsg({ tone: "red", text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy(false);
    }
  }

  if (!DEMO) return <Alert tone="amber">Demo controls exist only on the demo deployment.</Alert>;
  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error ?? "Could not load"}</Alert>;

  return (
    <>
      <PageHeader
        title="Demo controls"
        subtitle="Live voice spending guard and data reset for the public demo."
      />
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="grid gap-4 sm:grid-cols-4">
        <Stat
          label="Voice mode"
          value={data.mode === "live" ? "Live" : "Simulation"}
          hint={data.reason ?? undefined}
        />
        <Stat
          label="Spent this month"
          value={usd(data.spent_usd)}
          hint={`of ${usd(data.budget_usd)} budget`}
        />
        <Stat label="Remaining" value={usd(data.remaining_usd)} />
        <Stat label="Live calls today" value={`${data.calls_today} / ${data.max_calls_per_day}`} />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-semibold text-navy">Live voice</h2>
          <Checkbox
            label="Allow live browser calls"
            checked={data.enabled}
            onChange={(e) =>
              act(
                () => send("/admin/api/demo/voice", "PUT", { enabled: e.target.checked }),
                "Saved.",
              )
            }
          />
          <form
            className="mt-4 flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const n = Number(budget);
              if (Number.isFinite(n))
                act(() => send("/admin/api/demo/voice", "PUT", { budget_usd: n }), "Budget saved.");
            }}
          >
            <Field
              label="Monthly voice budget (USD)"
              hint={`Vapi's reported call cost. Operator ceiling: ${usd(data.budget_cap_usd)}.`}
            >
              <Input
                type="number"
                min={0}
                max={data.budget_cap_usd}
                step="0.5"
                placeholder={String(data.budget_usd)}
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
            </Field>
            <Button type="submit" variant="secondary" disabled={busy || budget === ""}>
              Save
            </Button>
          </form>
          {data.paused_until && (
            <div className="mt-4 space-y-2">
              <Alert tone="amber">
                Paused until {dateTime(data.paused_until)}. {data.reason}
              </Alert>
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  act(
                    () => send("/admin/api/demo/voice", "PUT", { clear_pause: true }),
                    "Pause cleared.",
                  )
                }
              >
                Clear pause
              </Button>
            </div>
          )}
        </Card>
        <Card>
          <h2 className="mb-1 font-semibold text-navy">Reset demo data</h2>
          <p className="mb-4 text-sm text-slate-600">
            Restores Houston Comfort HVAC and the second sample client, removes anything visitors
            added, and restores the demo sign-ins. The Vapi assistant is kept. Also runs
            automatically on a schedule.
          </p>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => act(() => send("/admin/api/demo/reset", "POST"), "Demo data reset.")}
          >
            Reset now
          </Button>
        </Card>
      </div>
    </>
  );
}
