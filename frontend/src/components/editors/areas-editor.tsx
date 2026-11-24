"use client";

import { useState } from "react";
import { Alert, Button, Card, Empty, Field, Input, SectionHeader, Spinner } from "@/components/ui";
import { api, send } from "@/lib/api";
import { useLoad } from "@/lib/use-load";

type Area = { id: string; zip_code: string; label: string | null };

export function AreasEditor({ base }: { base: string }) {
  const { data, error, loading, reload } = useLoad(() => api<Area[]>(`${base}/areas`), [base]);
  const [zips, setZips] = useState("");
  const [labelText, setLabel] = useState("");
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    const list = zips.split(/[\s,;]+/).filter(Boolean);
    try {
      const r = await send(`${base}/areas`, "POST", {
        zip_codes: list,
        label: labelText || null,
      });
      setMsg({ tone: "green", text: `Added ${(r as { added: number }).added} ZIP code(s).` });
      setZips("");
      await reload();
    } catch (err) {
      setMsg({ tone: "red", text: err instanceof Error ? err.message : "Could not add" });
    }
  }

  async function remove(id: string) {
    await send(`${base}/areas/${id}`, "DELETE");
    await reload();
  }

  return (
    <>
      <SectionHeader
        title="Service areas"
        subtitle="Your receptionist never claims coverage outside these ZIP codes."
      />
      <Card className="mb-6">
        <form onSubmit={add} className="grid gap-4 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <Field
              label="ZIP codes"
              hint="Paste several, separated by spaces, commas or new lines."
            >
              <Input
                required
                value={zips}
                onChange={(e) => setZips(e.target.value)}
                placeholder="77002 77003 77004"
              />
            </Field>
          </div>
          <Field label="Area name (optional)">
            <Input
              maxLength={100}
              value={labelText}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Downtown Houston"
            />
          </Field>
          <div className="sm:col-span-3 space-y-3">
            {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
            <Button type="submit">Add ZIP codes</Button>
          </div>
        </form>
      </Card>
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No service areas yet" />
        ) : (
          <ul className="flex flex-wrap gap-2">
            {data.map((a) => (
              <li
                key={a.id}
                className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-sm"
              >
                <span className="font-medium">{a.zip_code}</span>
                {a.label && <span className="text-slate-500">{a.label}</span>}
                <button
                  aria-label={`Remove ${a.zip_code}`}
                  className="text-slate-400 hover:text-red-600"
                  onClick={() => remove(a.id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
