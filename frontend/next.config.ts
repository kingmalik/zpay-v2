import type { NextConfig } from "next";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const CONCENTRA_ADDRESS = process.env.NEXT_PUBLIC_CONCENTRA_ADDRESS || process.env.CONCENTRA_ADDRESS || ''

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_API_URL: BACKEND_URL,
    NEXT_PUBLIC_CONCENTRA_ADDRESS: CONCENTRA_ADDRESS,
  },
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${BACKEND_URL}/:path*`,
      },
      {
        source: '/api/data/:path*',
        destination: `${BACKEND_URL}/api/data/:path*`,
      },
    ]
  },
};

export default nextConfig;
