import type { NextConfig } from "next";

const apiOrigin = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
const maxUploadMb = Number(process.env.MAX_UPLOAD_MB ?? "100");
const multipartLimit = maxUploadMb * 1024 * 1024 + 64 * 1024;
if (!Number.isSafeInteger(maxUploadMb) || maxUploadMb <= 0 || !Number.isSafeInteger(multipartLimit)) {
  throw new Error("MAX_UPLOAD_MB must be a positive integer within the supported byte range");
}

const nextConfig: NextConfig = {
  agentRules: false,
  experimental: {
    proxyClientMaxBodySize: multipartLimit,
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
