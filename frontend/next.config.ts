import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_BUILD_DIR || ".next",
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  experimental: { cpus: process.env.NEXT_BUILD_CPUS ? Number(process.env.NEXT_BUILD_CPUS) : undefined },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Keep browser requests same-origin. Next.js proxies API calls to FastAPI,
  // avoiding localhost/127.0.0.1 mismatches and browser CORS failures.
  async rewrites() {
    const apiOrigin = (process.env.API_PROXY_TARGET || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [{ source: "/backend-api/:path*", destination: `${apiOrigin}/:path*` }];
  },
};

export default nextConfig;
