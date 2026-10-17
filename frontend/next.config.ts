import type { NextConfig } from "next";

// The browser always calls same-origin `/api/...`. In dev (and any deployment without a
// reverse proxy in front) Next forwards those calls to the FastAPI backend.
const backendUrl = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      { source: "/media/:path*", destination: `${backendUrl}/media/:path*` },
    ];
  },
};

export default nextConfig;
