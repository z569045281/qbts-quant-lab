/**
 * Supabase client for the read-only deployed dashboard.
 *
 * The deployed site talks straight to Supabase with the public anon key
 * (RLS allows SELECT only). Writes happen exclusively from the local
 * `publish.py` using the service_role key — never from the browser.
 *
 * Env (set in .env.local for dev, in the Amplify console for prod):
 *   NEXT_PUBLIC_SUPABASE_URL
 *   NEXT_PUBLIC_SUPABASE_ANON_KEY
 */
import { createClient } from "@supabase/supabase-js";

const url  = process.env.NEXT_PUBLIC_SUPABASE_URL;
// New Supabase consoles call the anon key "publishable key" (sb_publishable_…);
// accept either env name.
const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
          || process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!url || !anon) {
  // Don't hard-crash the build when secrets are absent — queries will surface a
  // clear error at runtime instead. A placeholder keeps createClient happy.
  console.warn(
    "[supabase] NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY not set — dashboard data will not load.",
  );
}

export const supabase = createClient(
  url  ?? "https://placeholder.supabase.co",
  anon ?? "placeholder-anon-key",
);

/** True when running as the locked-down public deployment (set NEXT_PUBLIC_DEPLOY_READONLY=1). */
export const READONLY = process.env.NEXT_PUBLIC_DEPLOY_READONLY === "1";
