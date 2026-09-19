import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
      {
        source: "/docs",
        destination: `${BACKEND_URL}/api/docs`,
      },
      {
        source: "/s/:path*",
        destination: `${BACKEND_URL}/s/:path*`,
      },
      {
        source: "/openapi.json",
        destination: `${BACKEND_URL}/openapi.json`,
      },
      {
        source: "/screenshots/:path*",
        destination: `${BACKEND_URL}/screenshots/:path*`,
      },
    ];
  },
};

export default nextConfig;
