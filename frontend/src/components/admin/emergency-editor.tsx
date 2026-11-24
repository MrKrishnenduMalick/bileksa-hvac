"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, Field, Input } from "../ui";
import { send } from "@/lib/api";
import type { EmergencyRule } from "@/lib/types";

/** Per-client emergency rules. The fixed life-safety block is always spoken first and
 * cannot be edited here; these are approved additions and routing choices. */
export function EmergencyEditor({
  base,
  rules,
  onSaved,
}: {
  base: string;
  rules: EmergencyRule[];
  onSaved: () => Promise<void>;
}) {
  const [items, setItems] = useState<EmergencyRule[]>(rules);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const update = (i: number, patch: Partial<EmergencyRule>) =>
    setItems((prev) => prev.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function save() {
    setMsg(null);
    try {
      await send(base, "PATCH", {
        emergency_rules: items.map(({ key, label, transfer, instructions }) => ({
          key,
          label,
          transfer,
          instructions,
        })),
      });
      setMsg({ tone: "green", text: "Saved. The assistant is re-synced with the new categories." });
      await onSaved();
    } catch (err) {
      setMsg({ tone: "red", text: err instanceof Error ? err.message : "Could not save" });
    }
  }

  return (
    <Card>
      <h2 className="font-semibold text-navy">Emergency rules</h2>
      <p className="mb-4 mt-1 text-sm text-slate-600">
        Fixed safety instructions (gas, carbon monoxide, smoke, burning smell, sparks, dangerous
        malfunction) are always given first. Add only instructions the client has approved; the AI
        reads them word for word and never invents others.
      </p>
      {msg && (
        <div className="mb-4">
          <Alert tone={msg.tone}>{msg.text}</Alert>
        </div>
      )}
      <div className="space-y-4">
        {items.map((r, i) => (
          <div key={r.key} className="rounded-xl border border-slate-200 p-4">
            <div className="flex flex-wrap items-center gap-2">
              {r.builtin ? (
                <span className="font-medium text-navy">{r.label}</span>
              ) : (
                <Input
                  aria-label="Category name"
                  className="max-w-xs"
                  value={r.label}
                  onChange={(e) => update(i, { label: e.target.value })}
                />
              )}
              {r.builtin ? <Badge>Standard</Badge> : <Badge tone="blue">Custom</Badge>}
              {!r.builtin && (
                <Button
                  variant="danger"
                  onClick={() => setItems((prev) => prev.filter((_, j) => j !== i))}
                >
                  Remove
                </Button>
              )}
            </div>
            <div className="mt-3">
              <Checkbox
                label="Transfer to the emergency line (otherwise take an urgent callback)"
                checked={r.transfer}
                onChange={(e) => update(i, { transfer: e.target.checked })}
              />
            </div>
            <div className="mt-3">
              <Field
                label={
                  r.builtin
                    ? "Additional approved instructions (optional)"
                    : "Approved instructions (required)"
                }
              >
                <textarea
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
                  rows={2}
                  maxLength={600}
                  value={r.instructions}
                  onChange={(e) => update(i, { instructions: e.target.value })}
                />
              </Field>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex gap-2">
        <Button
          variant="secondary"
          onClick={() =>
            setItems((prev) => [
              ...prev,
              {
                key: `custom_${Date.now().toString(36)}`,
                label: "",
                builtin: false,
                transfer: true,
                instructions: "",
              },
            ])
          }
        >
          Add custom category
        </Button>
        <Button onClick={save}>Save emergency rules</Button>
      </div>
    </Card>
  );
}
