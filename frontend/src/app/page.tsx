import { SitePage } from "@/components/site";
import { ButtonLink } from "@/components/ui";
import { DEMO } from "@/lib/demo";

const FEATURES = [
  [
    "Answers every call",
    "Greets callers with your business name, day and night, so urgent jobs don't go to a competitor.",
  ],
  [
    "Knows your business",
    "Quotes only the services, price ranges, hours and ZIP codes you approve. No guessing.",
  ],
  [
    "Captures real leads",
    "Collects name, address, ZIP, the HVAC issue and urgency, and reads the callback number back.",
  ],
  [
    "Callbacks and transfers",
    "Transfers to your team when you allow it, or takes a callback request without promising times.",
  ],
  [
    "Safety first",
    "Recognises gas leaks, carbon monoxide alarms and electrical hazards and gives fixed safety guidance.",
  ],
  ["Keep your number", "Forward your existing business line. Nothing changes for your customers."],
];

const STEPS = [
  [
    "Talk to BILEKSA",
    "Tell us about your business. We recommend the right package for your call volume.",
  ],
  [
    "We set everything up",
    "Your services, hours, service areas, transfer and emergency rules, configured and tested by our team.",
  ],
  [
    "Forward your line",
    "Forward your existing number, place a test call, and you go live once it's verified.",
  ],
];

export default function Home() {
  return (
    <SitePage>
      <section className="mx-auto max-w-6xl px-4 pb-16 pt-16 sm:px-6 sm:pt-24">
        <p className="text-sm font-semibold uppercase tracking-wider text-brand">
          AI receptionist for HVAC contractors
        </p>
        <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight text-navy sm:text-5xl">
          Your HVAC Business. Your AI Receptionist.
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-slate-600">
          Never miss an important business call again. BILEKSA answers your calls, captures every
          lead and gets urgent jobs to your team, without you touching any technical setup.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          {DEMO && <ButtonLink href="/demo">Try the live demo</ButtonLink>}
          <ButtonLink href="/contact" variant={DEMO ? "secondary" : "primary"}>
            Talk to BILEKSA
          </ButtonLink>
          <ButtonLink href="/login" variant="secondary">
            Client sign in
          </ButtonLink>
        </div>
        <div className="glass mt-12 rounded-2xl p-5 sm:p-6">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Example call</p>
          <div className="mt-3 space-y-2 text-sm">
            <p>
              <span className="font-medium text-navy">Receptionist:</span> Thank you for calling ABC
              Heating & Cooling. This is your AI receptionist. How can I help you today?
            </p>
            <p>
              <span className="font-medium text-slate-700">Caller:</span> My AC stopped cooling. Do
              you come out to 77002?
            </p>
            <p>
              <span className="font-medium text-navy">Receptionist:</span> Yes, 77002 is in our
              service area. AC repair runs $89 to $450 depending on the problem. Can I take your
              name and the best number to reach you?
            </p>
          </div>
        </div>
      </section>
      <section className="bg-white/60 py-16" aria-labelledby="features">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <h2 id="features" className="text-2xl font-semibold text-navy">
            Everything a first-line receptionist does
          </h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(([t, d]) => (
              <div key={t} className="glass rounded-2xl p-5">
                <h3 className="font-semibold text-navy">{t}</h3>
                <p className="mt-1 text-sm text-slate-600">{d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6" aria-labelledby="how">
        <h2 id="how" className="text-2xl font-semibold text-navy">
          A managed service, live in three steps
        </h2>
        <ol className="mt-8 grid gap-4 sm:grid-cols-3">
          {STEPS.map(([t, d], i) => (
            <li key={t} className="glass rounded-2xl p-5">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-brand text-sm font-semibold text-white">
                {i + 1}
              </span>
              <h3 className="mt-3 font-semibold text-navy">{t}</h3>
              <p className="mt-1 text-sm text-slate-600">{d}</p>
            </li>
          ))}
        </ol>
        <div className="mt-10">
          <ButtonLink href="/contact">Get your AI receptionist</ButtonLink>
        </div>
      </section>
    </SitePage>
  );
}
