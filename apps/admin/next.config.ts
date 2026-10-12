import type { NextConfig } from "next";

// Production: a static export served by nginx, which also proxies /api/admin to Django on the
// same origin (doc 12: no CORS) and sets the security headers (frame-ancestors 'none', etc.).
// Development: `next dev` cannot use rewrites together with `output: "export"`, so the proxy
// is a dev-only rewrite to the local API.
const isBuild = process.env.NODE_ENV === "production";
const apiOrigin = process.env.ADMIN_API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = isBuild
  ? { output: "export", reactStrictMode: true, poweredByHeader: false, transpilePackages: ["@luxrocket/console-kit"] }
  : {
      reactStrictMode: true,
      poweredByHeader: false,
      transpilePackages: ["@luxrocket/console-kit"],
      async rewrites() {
        return [{ source: "/api/admin/:path*", destination: `${apiOrigin}/api/admin/:path*` }];
      },
    };

export default nextConfig;
