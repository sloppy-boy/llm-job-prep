import type { NextConfig } from "next";

const backendUrl = process.env.API_BACKEND_URL || "http://localhost:8000";
const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
