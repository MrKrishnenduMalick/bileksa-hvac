export const money = (cents: number | null | undefined) => {
  if (cents == null) return "—";
  const digits = cents % 100 === 0 ? 0 : 2;
  const text = (Math.abs(cents) / 100).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${cents < 0 ? "-" : ""}$${text}`;
};

export const dateTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "—";

export const duration = (seconds: number | null | undefined) => {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m}m ${s}s` : `${s}s`;
};

export const phone = (e164: string | null | undefined) => {
  if (!e164) return "—";
  const d = e164.replace(/\D/g, "").slice(-10);
  return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : e164;
};

export const label = (value: string | null | undefined) =>
  value ? value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "—";

export const day = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : "—";
