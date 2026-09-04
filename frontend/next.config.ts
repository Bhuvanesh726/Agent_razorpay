import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev server only fully trusts the "localhost" host by default; without
  // this, loading the app via 127.0.0.1 silently breaks client hydration
  // data streaming (page shell renders, but effects/fetches never run).
  allowedDevOrigins: ["127.0.0.1"],
  // Emits .next/standalone with only the files the server actually needs,
  // so the Docker runtime image doesn't carry the full node_modules tree.
  // Build-output only — `next dev` is unaffected.
  output: "standalone",
};

export default nextConfig;
