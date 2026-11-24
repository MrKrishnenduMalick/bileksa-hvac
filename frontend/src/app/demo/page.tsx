import type { Metadata } from "next";
import { SitePage } from "@/components/site";
import { DemoSignIn } from "./sign-in";

export const metadata: Metadata = { title: "Live demo" };

export default function DemoPage() {
  return (
    <SitePage>
      <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
        <p className="text-sm font-semibold uppercase tracking-wider text-brand">Live demo</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-navy">
          Houston Comfort HVAC
        </h1>
        <p className="mt-4 text-slate-600">
          This is the real BILEKSA product running on its own demo database with a fictional HVAC
          company. Sign in as the business owner to see calls, leads, callbacks and usage, and talk
          to the AI receptionist from your browser. Sign in as the BILEKSA admin to see client
          management, packages, costs and the demo controls.
        </p>
        <DemoSignIn />
        <ul className="mt-10 list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>Everything you change is reset automatically; please don&apos;t enter real data.</li>
          <li>Phone forwarding is switched off. Voice runs in the browser.</li>
          <li>
            Live voice has a small monthly budget. When it is used up, the receptionist switches to
            a clearly labelled simulation that runs the same lead, callback and emergency logic.
          </li>
          <li>The first load can take up to a minute while the free demo server wakes up.</li>
        </ul>
      </section>
    </SitePage>
  );
}
