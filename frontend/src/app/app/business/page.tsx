"use client";

import { useSession } from "@/components/session";
import { Alert, Badge, Card, Empty, PageHeader, Spinner, Table, Td } from "@/components/ui";
import { api } from "@/lib/api";
import { label, money, phone } from "@/lib/format";
import type { Faq, PhoneLine, Service } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
type Hours = { weekday: number; open_time: string; close_time: string };
type Area = { id: string; zip_code: string; label: string | null };

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{k}</dt>
      <dd className="mt-0.5 text-sm">{v || "—"}</dd>
    </div>
  );
}

/** What the AI receptionist knows about the business. Read-only: BILEKSA makes changes. */
export default function BusinessInfoPage() {
  const { me } = useSession();
  const b = me.business;
  const services = useLoad(() => api<Service[]>("/api/business/services"));
  const hours = useLoad(() => api<Hours[]>("/api/business/hours"));
  const areas = useLoad(() => api<Area[]>("/api/business/areas"));
  const faqs = useLoad(() => api<Faq[]>("/api/business/faqs"));
  const line = useLoad(() => api<PhoneLine>("/api/phone"));
  if (!b) return <Spinner />;

  return (
    <>
      <PageHeader
        title="Business info"
        subtitle="Everything your AI receptionist uses to answer calls. To change anything, contact BILEKSA support."
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-semibold text-navy">Profile and routing</h2>
          <dl className="grid gap-3 sm:grid-cols-2">
            <Row k="Business name" v={b.name} />
            <Row
              k="Contact"
              v={[b.contact_email, phone(b.contact_phone)]
                .filter((x) => x && x !== "—")
                .join(" · ")}
            />
            <Row k="Address" v={b.address} />
            <Row k="Time zone" v={b.timezone} />
            <Row k="Transfer (direct line)" v={phone(b.transfer_number)} />
            <Row k="Backup / fallback number" v={phone(b.fallback_number)} />
            <Row k="Emergency line" v={phone(b.emergency_number)} />
            <Row k="Notifications sent to" v={b.notification_email ?? b.contact_email} />
          </dl>
        </Card>
        <Card>
          <h2 className="mb-3 font-semibold text-navy">Phone line</h2>
          {line.loading ? (
            <Spinner />
          ) : !line.data ? (
            <Empty title="Not connected yet">
              BILEKSA assigns your forwarding number during setup.
            </Empty>
          ) : (
            <>
              <dl className="grid gap-3 sm:grid-cols-2">
                <Row k="Your business number" v={phone(line.data.business_number)} />
                <Row k="Forward to (BILEKSA)" v={phone(line.data.destination_number)} />
                <Row
                  k="Status"
                  v={
                    <Badge tone={line.data.state === "verified" ? "green" : "amber"}>
                      {label(line.data.state)}
                    </Badge>
                  }
                />
              </dl>
              <ol className="mt-4 list-decimal space-y-1 pl-5 text-sm text-slate-700">
                {line.data.steps.map((s) => (
                  <li key={s}>{s.replace(/\*\*/g, "")}</li>
                ))}
              </ol>
            </>
          )}
        </Card>
        <Card>
          <h2 className="mb-3 font-semibold text-navy">Hours</h2>
          {hours.data && hours.data.length > 0 ? (
            <ul className="space-y-1 text-sm">
              {DAYS.map((d, i) => {
                const h = hours.data?.find((x) => x.weekday === i);
                return (
                  <li key={d} className="flex justify-between">
                    <span>{d}</span>
                    <span>
                      {h ? `${h.open_time.slice(0, 5)} – ${h.close_time.slice(0, 5)}` : "Closed"}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <Empty title="Hours not set" />
          )}
        </Card>
        <Card>
          <h2 className="mb-3 font-semibold text-navy">Service areas</h2>
          {areas.data && areas.data.length > 0 ? (
            <p className="text-sm">{areas.data.map((a) => a.zip_code).join(", ")}</p>
          ) : (
            <Empty title="No service areas set" />
          )}
        </Card>
      </div>
      <Card className="mt-6">
        <h2 className="mb-3 font-semibold text-navy">Services and approved prices</h2>
        {services.error && <Alert>{services.error}</Alert>}
        {services.data && services.data.length > 0 ? (
          <Table head={["Service", "Price range", "Note"]}>
            {services.data.map((s) => (
              <tr key={s.id}>
                <Td>{s.name}</Td>
                <Td>
                  {s.price_min_cents == null && s.price_max_cents == null
                    ? "—"
                    : s.price_min_cents === s.price_max_cents
                      ? money(s.price_min_cents)
                      : `${money(s.price_min_cents)} – ${money(s.price_max_cents)}`}
                </Td>
                <Td>{s.price_note ?? "—"}</Td>
              </tr>
            ))}
          </Table>
        ) : (
          <Empty title="No services set" />
        )}
      </Card>
      <Card className="mt-6">
        <h2 className="mb-3 font-semibold text-navy">FAQs and policies</h2>
        {faqs.data && faqs.data.length > 0 ? (
          <dl className="space-y-3">
            {faqs.data
              .filter((f) => f.active)
              .map((f) => (
                <div key={f.id}>
                  <dt className="font-medium text-navy">
                    {f.question} {f.category === "policy" && <Badge>Policy</Badge>}
                  </dt>
                  <dd className="text-sm text-slate-700">{f.answer}</dd>
                </div>
              ))}
          </dl>
        ) : (
          <Empty title="No FAQs yet" />
        )}
      </Card>
      <Card className="mt-6">
        <h2 className="mb-3 font-semibold text-navy">Emergency handling</h2>
        <p className="mb-3 text-sm text-slate-600">
          Fixed life-safety instructions are always given first. These are your business&apos;s
          additional rules.
        </p>
        <Table head={["Category", "Transfer to emergency line", "Additional instructions"]}>
          {b.emergency_rules.map((r) => (
            <tr key={r.key}>
              <Td>{r.label}</Td>
              <Td>{r.transfer ? "Yes" : "No, callback"}</Td>
              <Td className="max-w-md text-sm">{r.instructions || "—"}</Td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
