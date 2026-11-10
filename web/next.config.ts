import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          // Framing only: a full script/style CSP would need per-request nonces.
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          // The noise editor records from the microphone, so it is not restricted.
          { key: "Permissions-Policy", value: "camera=(), geolocation=()" },
        ],
      },
      {
        // Only when a TLS-terminating proxy reports HTTPS, so plain http://localhost is never pinned.
        source: "/:path*",
        has: [{ type: "header", key: "x-forwarded-proto", value: "https" }],
        headers: [{ key: "Strict-Transport-Security", value: "max-age=31536000" }],
      },
    ];
  },
};

export default nextConfig;
