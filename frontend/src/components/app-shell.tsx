"use client";

import { DEMO } from "@/lib/demo";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Logo } from "./brand";
import { signOut, useSession } from "./session";

export type NavItem = { href: string; label: string };

const CUSTOMER_NAV: NavItem[] = [
  { href: "/app", label: "Overview" },
  { href: "/app/calls", label: "Call history" },
  { href: "/app/leads", label: "Leads" },
  { href: "/app/callbacks", label: "Callbacks & appointments" },
  { href: "/app/usage", label: "Usage" },
  { href: "/app/packages", label: "Packages" },
  { href: "/app/notifications", label: "Notifications" },
  { href: "/app/business", label: "Business info" },
  ...(DEMO ? [{ href: "/app/try", label: "Try the receptionist" }] : []),
];

const ADMIN_NAV: NavItem[] = [
  { href: "/admin", label: "Clients" },
  { href: "/admin/upgrades", label: "Upgrade requests" },
  { href: "/admin/usage", label: "Usage & limits" },
  { href: "/admin/packages", label: "Packages" },
  { href: "/admin/costs", label: "Costs & profit" },
  { href: "/admin/notifications", label: "Notifications" },
  { href: "/admin/vapi", label: "Vapi tools" },
  { href: "/admin/errors", label: "Errors" },
  { href: "/admin/audit", label: "Audit log" },
  ...(DEMO ? [{ href: "/admin/demo", label: "Demo controls" }] : []),
];

export function AppShell({ admin = false, children }: { admin?: boolean; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  const nav = admin ? ADMIN_NAV : CUSTOMER_NAV;
  const root = admin ? "/admin" : "/app";

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <aside className="border-b border-slate-200/70 bg-navy text-white lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between px-5 py-4">
          <Logo light />
          <button
            className="rounded-lg px-2 py-1 text-sm text-white/80 ring-1 ring-white/20 lg:hidden"
            aria-expanded={open}
            aria-controls="main-nav"
            onClick={() => setOpen(!open)}
          >
            Menu
          </button>
        </div>
        <nav
          id="main-nav"
          className={`${open ? "block" : "hidden"} px-3 pb-4 lg:block`}
          aria-label="Main"
        >
          {admin && (
            <p className="px-3 pb-2 text-xs font-semibold uppercase tracking-wider text-white/50">
              BILEKSA admin
            </p>
          )}
          <ul className="space-y-0.5">
            {nav.map((item) => {
              const active =
                item.href === root
                  ? pathname === root || pathname.startsWith("/admin/client")
                  : pathname.startsWith(item.href) ||
                    (item.href === "/app/leads" && pathname.startsWith("/app/lead"));
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={() => setOpen(false)}
                    aria-current={active ? "page" : undefined}
                    className={`block rounded-lg px-3 py-2 text-sm transition ${active ? "bg-white/15 font-medium text-white" : "text-white/75 hover:bg-white/10 hover:text-white"}`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="mt-6 border-t border-white/10 px-3 pt-4 text-xs text-white/60">
            <p className="truncate">{me.user.email}</p>
            {me.is_admin && !admin && (
              <Link href="/admin" className="mt-2 block text-white/80 hover:text-white">
                Admin area →
              </Link>
            )}
            {admin && me.business && (
              <Link href="/app" className="mt-2 block text-white/80 hover:text-white">
                Customer view →
              </Link>
            )}
            <button className="mt-2 text-white/80 hover:text-white" onClick={() => signOut(router)}>
              Sign out
            </button>
          </div>
        </nav>
      </aside>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-8 sm:py-10">{children}</main>
    </div>
  );
}
