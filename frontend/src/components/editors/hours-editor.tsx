"use client";

import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Field,
  Input,
  SectionHeader,
  Spinner,
  Table,
  Td,
} from "@/components/ui";
import { api, send } from "@/lib/api";
import { useLoad } from "@/lib/use-load";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
type Hours = { weekday: number; open_time: string; close_time: string };
type Holiday = {
  id: string;
  date: string;
  label: string;
  closed: boolean;
  open_time: string | null;
  close_time: string | null;
};
type Row = { open: boolean; from: string; to: string };

const toRows = (data: Hours[]): Row[] =>
  DAYS.map((_, i) => {
    const h = data.find((x) => x.weekday === i);
    return h
      ? { open: true, from: h.open_time.slice(0, 5), to: h.close_time.slice(0, 5) }
      : { open: false, from: "08:00", to: "17:00" };
  });

export function HoursEditor({ base }: { base: string }) {
  const hours = useLoad(() => api<Hours[]>(`${base}/hours`), [base]);
  if (hours.loading) return <Spinner />;
  if (hours.error || !hours.data) return <Alert>{hours.error}</Alert>;
  return <HoursForm base={base} initial={toRows(hours.data)} />;
}

function HoursForm({ base, initial }: { base: string; initial: Row[] }) {
  const holidays = useLoad(() => api<Holiday[]>(`${base}/holidays`), [base]);
  const [rows, setRows] = useState<Row[]>(initial);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [hol, setHol] = useState({
    date: "",
    label: "",
    closed: true,
    open_time: "09:00",
    close_time: "13:00",
  });

  async function saveHours() {
    setMsg(null);
    try {
      await send(
        `${base}/hours`,
        "PUT",
        rows.flatMap((r, i) =>
          r.open ? [{ weekday: i, open_time: r.from, close_time: r.to }] : [],
        ),
      );
      setMsg({ tone: "green", text: "Business hours saved." });
    } catch (e) {
      setMsg({ tone: "red", text: e instanceof Error ? e.message : "Could not save" });
    }
  }

  async function addHoliday(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      await send(`${base}/holidays`, "POST", {
        date: hol.date,
        label: hol.label,
        closed: hol.closed,
        open_time: hol.closed ? null : hol.open_time,
        close_time: hol.closed ? null : hol.close_time,
      });
      setHol({ ...hol, date: "", label: "" });
      await holidays.reload();
    } catch (err) {
      setMsg({ tone: "red", text: err instanceof Error ? err.message : "Could not add" });
    }
  }

  return (
    <>
      <SectionHeader
        title="Hours & holidays"
        subtitle="Used for “are you open?” answers and for transfer rules."
      />
      {msg && (
        <div className="mb-4">
          <Alert tone={msg.tone}>{msg.text}</Alert>
        </div>
      )}
      <Card className="mb-6">
        <div className="space-y-3">
          {DAYS.map((d, i) => (
            <div
              key={d}
              className="grid grid-cols-[7rem_auto_1fr] items-center gap-3 sm:grid-cols-[8rem_7rem_8rem_8rem]"
            >
              <span className="text-sm font-medium">{d}</span>
              <Checkbox
                label="Open"
                checked={rows[i].open}
                onChange={(e) =>
                  setRows(rows.map((r, j) => (j === i ? { ...r, open: e.target.checked } : r)))
                }
              />
              {rows[i].open ? (
                <>
                  <Input
                    aria-label={`${d} opens`}
                    type="time"
                    value={rows[i].from}
                    onChange={(e) =>
                      setRows(rows.map((r, j) => (j === i ? { ...r, from: e.target.value } : r)))
                    }
                  />
                  <Input
                    aria-label={`${d} closes`}
                    type="time"
                    value={rows[i].to}
                    onChange={(e) =>
                      setRows(rows.map((r, j) => (j === i ? { ...r, to: e.target.value } : r)))
                    }
                  />
                </>
              ) : (
                <span className="text-sm text-slate-400">Closed</span>
              )}
            </div>
          ))}
        </div>
        <Button className="mt-5" onClick={saveHours}>
          Save hours
        </Button>
      </Card>
      <Card>
        <h2 className="mb-3 font-semibold text-navy">Holiday closures</h2>
        <form onSubmit={addHoliday} className="mb-5 grid gap-3 sm:grid-cols-4">
          <Field label="Date">
            <Input
              type="date"
              required
              value={hol.date}
              onChange={(e) => setHol({ ...hol, date: e.target.value })}
            />
          </Field>
          <Field label="Name">
            <Input
              required
              maxLength={100}
              value={hol.label}
              onChange={(e) => setHol({ ...hol, label: e.target.value })}
              placeholder="Thanksgiving"
            />
          </Field>
          <div className="flex items-end pb-2">
            <Checkbox
              label="Closed all day"
              checked={hol.closed}
              onChange={(e) => setHol({ ...hol, closed: e.target.checked })}
            />
          </div>
          {!hol.closed && (
            <div className="flex gap-2">
              <Input
                aria-label="Opens"
                type="time"
                value={hol.open_time}
                onChange={(e) => setHol({ ...hol, open_time: e.target.value })}
              />
              <Input
                aria-label="Closes"
                type="time"
                value={hol.close_time}
                onChange={(e) => setHol({ ...hol, close_time: e.target.value })}
              />
            </div>
          )}
          <div className="sm:col-span-4">
            <Button type="submit" variant="secondary">
              Add holiday
            </Button>
          </div>
        </form>
        {holidays.data && holidays.data.length === 0 ? (
          <Empty title="No holidays added" />
        ) : (
          <Table head={["Date", "Name", "Hours", ""]}>
            {(holidays.data ?? []).map((h) => (
              <tr key={h.id}>
                <Td>{h.date}</Td>
                <Td>{h.label}</Td>
                <Td>
                  {h.closed
                    ? "Closed"
                    : `${h.open_time?.slice(0, 5)} – ${h.close_time?.slice(0, 5)}`}
                </Td>
                <Td className="text-right">
                  <Button
                    variant="danger"
                    onClick={async () => {
                      await send(`${base}/holidays/${h.id}`, "DELETE");
                      await holidays.reload();
                    }}
                  >
                    Remove
                  </Button>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
