import type { NextConfig } from "next";

// The site is exported as static files (out/) and served by Cloudflare Pages. All data comes
// from the BILEKSA API at runtime, so nothing needs a Node server. Security headers are written
// to public/_headers by scripts/write-headers.mjs because a static export ignores headers().
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
