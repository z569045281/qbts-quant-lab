/**
 * Backend API base URL.
 *
 * Priority:
 *   1. NEXT_PUBLIC_API_URL env var (explicit override)
 *   2. Same host as the page, port 8000 — so accessing the app from another
 *      device on the LAN (e.g. an iPad at 192.168.1.109:3000) hits the backend
 *      at 192.168.1.109:8000 instead of the device's own localhost.
 *   3. localhost:8000 fallback (SSR / build time).
 */
export const API =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : "http://localhost:8000");
