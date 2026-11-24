import type { Metadata } from "next";
import { SitePage } from "@/components/site";

export const metadata: Metadata = { title: "Privacy policy" };

export default function Page() {
  return (
    <SitePage>
      <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
        <h1 className="text-3xl font-semibold text-navy">Privacy policy</h1>
        <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          This page must be written and approved by a lawyer before launch (plan assumption A12: AI
          disclosure, call recording and transcript consent, data retention).
        </p>
      </section>
    </SitePage>
  );
}
