import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Keep production output separate from the dev cache. This also makes clean
  // CI builds deterministic when a dev server still owns `.next` on Windows.
  distDir: ".next-build",
};

export default nextConfig;
