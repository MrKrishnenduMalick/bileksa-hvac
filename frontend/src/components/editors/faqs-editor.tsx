"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, Empty, Field, Input, Select, Spinner } from "../ui";
import { api, send } from "@/lib/api";
import type { Faq } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

const blank = { category: "faq", question: "", answer: "", active: true };

/** FAQs and policies the AI may repeat word for word. */
export function FaqsEditor({ base }: { base: string }) {
  const { data, error, loading, reload } = useLoad(() => api<Faq[]>(`${base}/faqs`), [base]);
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      if (editing) await send(`${base}/faqs/${editing}`, "PATCH", form);
      else await send(`${base}/faqs`, "POST", form);
      setForm(blank);
      setEditing(null);
      await reload();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not save");
    }
  }

  return (
    <>
      <Card className="mb-6">
        <h2 className="mb-3 font-semibold text-navy">
          {editing ? "Edit entry" : "Add an FAQ or policy"}
        </h2>
        <form onSubmit={save} className="grid gap-4 sm:grid-cols-4">
          <Field label="Type">
            <Select
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
            >
              <option value="faq">FAQ</option>
              <option value="policy">Policy</option>
            </Select>
          </Field>
          <div className="sm:col-span-3">
            <Field label="Question or policy name">
              <Input
                required
                minLength={3}
                maxLength={300}
                value={form.question}
                onChange={(e) => setForm({ ...form, question: e.target.value })}
              />
            </Field>
          </div>
          <div className="sm:col-span-4">
            <Field label="Approved answer">
              <textarea
                required
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
                rows={3}
                maxLength={1500}
                value={form.answer}
                onChange={(e) => setForm({ ...form, answer: e.target.value })}
              />
            </Field>
          </div>
          <Checkbox
            label="Active"
            checked={form.active}
            onChange={(e) => setForm({ ...form, active: e.target.checked })}
          />
          <div className="flex gap-2 sm:col-span-4">
            {msg && <Alert>{msg}</Alert>}
            <Button type="submit">{editing ? "Save" : "Add"}</Button>
            {editing && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setEditing(null);
                  setForm(blank);
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      </Card>
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.length === 0 ? (
          <Empty title="No FAQs yet">Without FAQs the AI says the team will follow up.</Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.map((f) => (
              <li key={f.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                <div className="max-w-2xl">
                  <p className="font-medium text-navy">
                    {f.question} {f.category === "policy" && <Badge>Policy</Badge>}{" "}
                    {!f.active && <Badge tone="amber">Inactive</Badge>}
                  </p>
                  <p className="text-sm text-slate-700">{f.answer}</p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setEditing(f.id);
                      setForm({
                        category: f.category,
                        question: f.question,
                        answer: f.answer,
                        active: f.active,
                      });
                    }}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="danger"
                    onClick={async () => {
                      await send(`${base}/faqs/${f.id}`, "DELETE");
                      await reload();
                    }}
                  >
                    Remove
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
