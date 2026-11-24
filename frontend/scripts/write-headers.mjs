// Writes public/_headers for Cloudflare Pages (a static export ignores next.config headers()).
// Run automatically by `npm run build`; reads the same NEXT_PUBLIC_* values as the app.
import { mkdirSync, writeFileSync } from "node:fs";

const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const supabase = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const demo = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// Browser voice (demo only) uses Vapi + Daily WebRTC; client deployments don't need it.
const voiceConnect = demo ? "https://api.vapi.ai https://*.daily.co wss://*.daily.co" : "";
const voiceScript = demo ? "https://c.daily.co" : "";

const csp = [
  "default-src 'self'",
  // Next.js injects small inline scripts for hydration, so script-src keeps 'unsafe-inline'.
  `script-src 'self' 'unsafe-inline' ${voiceScript}`.trim(),
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self' ${api} ${supabase} ${voiceConnect}`.replace(/\s+/g, " ").trim(),
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const headers = `/*
  Content-Security-Policy: ${csp}
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), geolocation=(), microphone=${demo ? "(self)" : "()"}
  Strict-Transport-Security: max-age=63072000; includeSubDomains

/_next/static/*
  Cache-Control: public, max-age=31536000, immutable
`;
mkdirSync(new URL("../public/", import.meta.url), { recursive: true });
writeFileSync(new URL("../public/_headers", import.meta.url), headers);
console.log(`public/_headers written (demo voice ${demo ? "allowed" : "off"})`);
