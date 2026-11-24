import Link from "next/link";

export function Logo({ light = false }: { light?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2" aria-label="BILEKSA HVAC home">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand to-navy text-sm font-bold text-white">
        B
      </span>
      <span
        className={`text-base font-semibold tracking-tight ${light ? "text-white" : "text-navy"}`}
      >
        BILEKSA <span className="text-brand">HVAC</span>
      </span>
    </Link>
  );
}
