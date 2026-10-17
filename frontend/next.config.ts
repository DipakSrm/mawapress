import type { NextConfig } from "next";

// The browser always calls same-origin `/api/...`. In dev (and any deployment without a
// reverse proxy in front) Next forwards those calls to the FastAPI backend.
const backendUrl = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

/** Hardening for the admin console: it is never framed by another site and never sniffed. */
export const ADMIN_SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: "frame-ancestors 'self'" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
];

const nextConfig: NextConfig = {
  async headers() {
    return [{ source: "/admin/:path*", headers: ADMIN_SECURITY_HEADERS }];
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      { source: "/media/:path*", destination: `${backendUrl}/media/:path*` },
    ];
  },
};

export default nextConfig;
