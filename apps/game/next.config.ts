import type { NextConfig } from "next";

// The game is a static export served from the CDN (ADR-017). Security headers, including the
// per-operator CSP frame-ancestors, are set on the launch document by the platform (doc 11 §6),
// not here.
const nextConfig: NextConfig = {
  output: "export",
  reactStrictMode: true,
  poweredByHeader: false,
  transpilePackages: ["@luxrocket/game-core", "@luxrocket/protocol"],
};

export default nextConfig;
