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

-- ── decision_journal ─────────────────────────────────────────────────────────
-- One row per recorded daily decision — the persisted track record + reflections.
-- Replaces the old local JSONL file so the journal survives across stateless
-- cloud (Lambda) runs, whose /tmp is wiped on every cold start. Written by
-- publish/refresh with the secret key (bypasses RLS); `data` holds the full
-- record (date, action, conviction, price, result/reflection, ...).
create table if not exists public.decision_journal (
  id         text primary key,
  updated_at timestamptz not null default now(),
  data       jsonb not null
);

alter table public.decision_journal enable row level security;

drop policy if exists "anon read decision_journal" on public.decision_journal;
create policy "anon read decision_journal"
  on public.decision_journal for select
  to anon, authenticated
  using (true);

-- ── predictions ──────────────────────────────────────────────────────────────
-- One row per day's meta-model prediction (was data/cache/predictions.jsonl).
-- Persisted in Supabase so the self-learning calibration survives stateless
-- cloud (Lambda) runs — /tmp is wiped each cold start, which would otherwise
-- reset the learned weights to nothing forever. Backend-only: written AND read
-- with the secret key (bypasses RLS); NOT exposed to the anon frontend.
-- `id` = the prediction's as_of date (YYYY-MM-DD); `data` = full record.
create table if not exists public.predictions (
  id         text primary key,
  updated_at timestamptz not null default now(),
  data       jsonb not null
);
alter table public.predictions enable row level security;
-- No anon policy on purpose: only the secret-key backend touches this table.

-- ── source_weights ───────────────────────────────────────────────────────────
-- Single row (id='current') holding the learned per-source weight multipliers
-- (was data/cache/source_weights.json). Same backend-only, secret-key model.
create table if not exists public.source_weights (
  id         text primary key,
  updated_at timestamptz not null default now(),
  data       jsonb not null
);
alter table public.source_weights enable row level security;

-- ── live_quote ───────────────────────────────────────────────────────────────
-- Single-row table (id=1) updated by quote_pusher.py every ~60s during US
-- trading hours (incl. pre/post). The dashboard polls it for a live header.
create table if not exists public.live_quote (
  id         int primary key,
  updated_at timestamptz not null default now(),
  data       jsonb not null
);

alter table public.live_quote enable row level security;

drop policy if exists "anon read live_quote" on public.live_quote;
create policy "anon read live_quote"
  on public.live_quote for select
  to anon, authenticated
  using (true);
