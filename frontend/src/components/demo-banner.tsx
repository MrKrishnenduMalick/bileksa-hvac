import Link from "next/link";
import { DEMO } from "@/lib/demo";

/** Shown on every page of the public demo so nobody mistakes it for a real client account. */
export function DemoBanner() {
  if (!DEMO) return null;
  return (
    <div className="bg-amber-100 px-4 py-2 text-center text-sm text-amber-950" role="note">
      <strong>Public demo.</strong> Houston Comfort HVAC is a fictional company; data resets
      regularly and phone forwarding is turned off.{" "}
      <Link href="/demo" className="font-medium underline">
        Demo sign-ins
      </Link>
    </div>
  );
}
