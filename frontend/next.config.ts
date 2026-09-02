import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev server only fully trusts the "localhost" host by default; without
  // this, loading the app via 127.0.0.1 silently breaks client hydration
  // data streaming (page shell renders, but effects/fetches never run).
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
