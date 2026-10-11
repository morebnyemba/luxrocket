import type { NextConfig } from "next";

// Production: a static export served by nginx, which also proxies /api/portal to Django on the
// same origin (doc 13: no CORS) and sets the security headers (frame-ancestors 'none', etc.).
// Development: `next dev` cannot use rewrites together with `output: "export"`, so the proxy
// is a dev-only rewrite to the local API.
const isBuild = process.env.NODE_ENV === "production";
const apiOrigin = process.env.PORTAL_API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = isBuild
  ? { output: "export", reactStrictMode: true, poweredByHeader: false }
  : {
      reactStrictMode: true,
      poweredByHeader: false,
      async rewrites() {
        return [{ source: "/api/portal/:path*", destination: `${apiOrigin}/api/portal/:path*` }];
      },
    };

export default nextConfig;
