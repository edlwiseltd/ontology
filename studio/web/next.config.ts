import type { NextConfig } from "next";

// Studio talks to the Autology platform only through /platform/* and /w/* (see lib/forward.ts). The policy below
// allows same-origin connections only. Next.js needs inline scripts for hydration and React Flow sets inline
// styles, hence 'unsafe-inline'; a nonce-based policy is a planned hardening step (see the frontend ADR).
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'" + (process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""),
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const config: NextConfig = {
  poweredByHeader: false,
  // Studio shows no raster images: the optimiser (and its optional sharp/libvips dependency, LGPL-3.0) is never used
  images: { unoptimized: true },
  reactStrictMode: true,
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "Content-Security-Policy", value: CSP },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "X-Frame-Options", value: "DENY" },
      ],
    }];
  },
};

export default config;
