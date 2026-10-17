import { describe, expect, it } from "vitest";
import nextConfig, { ADMIN_SECURITY_HEADERS } from "../../next.config";

describe("admin security headers", () => {
  it("applies the four hardening headers to every /admin path", async () => {
    const rules = await nextConfig.headers!();
    const admin = rules.find((r) => r.source === "/admin/:path*");
    expect(admin).toBeDefined();
    const byKey = Object.fromEntries(admin!.headers.map((h) => [h.key, h.value]));
    expect(byKey).toEqual({
      "Content-Security-Policy": "frame-ancestors 'self'",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "strict-origin-when-cross-origin",
      "X-Frame-Options": "SAMEORIGIN",
    });
    expect(ADMIN_SECURITY_HEADERS).toHaveLength(4);
  });
});
