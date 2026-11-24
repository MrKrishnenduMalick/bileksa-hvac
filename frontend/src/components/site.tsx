import Link from "next/link";
import type { ReactNode } from "react";
import { Logo } from "./brand";
import { CONTACT } from "@/lib/contact";
import { DEMO } from "@/lib/demo";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-slate-200/60 bg-white/70 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
        <Logo />
        <nav aria-label="Site" className="flex items-center gap-1 text-sm sm:gap-4">
          {DEMO && (
            <Link
              href="/demo"
              className="rounded-lg px-2 py-1 font-medium text-brand hover:text-navy"
            >
              Live demo
            </Link>
          )}
          <Link href="/login" className="rounded-lg px-2 py-1 text-slate-700 hover:text-navy">
            Client sign in
          </Link>
          <Link
            href="/contact"
            className="rounded-xl bg-brand px-3 py-1.5 font-medium text-white hover:bg-brand-600"
          >
            Talk to BILEKSA
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-auto bg-navy text-white/70">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-sm sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <Logo light />
        <p>Your HVAC Business. Your AI Receptionist. · {CONTACT.city}</p>
        <div className="flex gap-4">
          <Link href="/privacy" className="hover:text-white">
            Privacy
          </Link>
          <Link href="/terms" className="hover:text-white">
            Terms
          </Link>
          <Link href="/contact" className="hover:text-white">
            Contact
          </Link>
        </div>
      </div>
    </footer>
  );
}

export function SitePage({ children }: { children: ReactNode }) {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </>
  );
}
