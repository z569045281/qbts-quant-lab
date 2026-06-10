-- QBTS Factor Miner — Supabase schema for the read-only deployed dashboard.
-- Run this ONCE in the Supabase SQL Editor (Dashboard → SQL Editor → New query).
--
-- Model: `publish.py` writes here with the service_role key (bypasses RLS).
-- The deployed Next.js frontend reads with the anon key (RLS allows SELECT only).

-- ── dashboard_state ─────────────────────────────────────────────────────────
-- One row per `publish.py` run. The frontend reads the most recent row.
-- `snapshot`    = full payload of GET /dashboard/snapshot (brief is nested inside)
-- `calibration` = full payload of GET /dashboard/calibration
create table if not exists public.dashboard_state (
  id           bigint generated always as identity primary key,
  published_at timestamptz not null default now(),
  snapshot     jsonb       not null,
  calibration  jsonb
);

create index if not exists dashboard_state_published_at_idx
  on public.dashboard_state (published_at desc);

-- ── factors ─────────────────────────────────────────────────────────────────
-- One row per mined factor. Replaced wholesale on each publish.
-- `data`  = factor entry from get_leaderboard() (metrics, name, freq, type, ...)
-- `code`  = factor source code
-- `chart` = payload of GET /factors/{id}/chart (ohlcv / markers / split_time)
create table if not exists public.factors (
  id           text primary key,
  published_at timestamptz not null default now(),
  score        double precision,
  data         jsonb not null,
  code         text,
  chart        jsonb
);

create index if not exists factors_score_idx
  on public.factors (score desc);

-- ── Row Level Security: anon may read, nobody may write via anon/public ──────
alter table public.dashboard_state enable row level security;
alter table public.factors         enable row level security;

drop policy if exists "anon read dashboard_state" on public.dashboard_state;
create policy "anon read dashboard_state"
  on public.dashboard_state for select
  to anon, authenticated
  using (true);

drop policy if exists "anon read factors" on public.factors;
create policy "anon read factors"
  on public.factors for select
  to anon, authenticated
  using (true);
