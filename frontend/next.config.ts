import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Fully static site (HTML/CSS/JS in `out/`) — the deployed dashboard is pure
  // client-side and reads straight from Supabase, so no Node server is needed.
  // Deployable to GitHub Pages / AWS Amplify / any static host.
  output: "export",

  // GitHub Pages serves project sites under /<repo-name>/ — the deploy
  // workflow sets NEXT_PUBLIC_BASE_PATH=/<repo>; local dev leaves it empty.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",

  // next/image optimization needs a server; not used on a static host.
  images: { unoptimized: true },

  // Allow accessing the dev server from other devices on the LAN (iPad/phone).
  // Without this, Next.js 16 blocks cross-origin dev resources from non-localhost
  // hosts, which breaks client hydration → the page freezes on its loading state.
  allowedDevOrigins: ["192.168.1.109", "192.168.1.*", "192.168.0.*", "10.0.0.*"],
};

export default nextConfig;
