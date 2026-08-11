import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Proxy API calls to the Python backend during development
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
  // Allow long-running API calls (LLM generation can take 30-60s)
  experimental: {
    proxyTimeout: 120_000, // 2 minutes for LLM batch operations
  },
};

export default nextConfig;
