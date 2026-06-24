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

-- ── watchlist_scan ───────────────────────────────────────────────────────────
-- Single row (id='current') holding the daily multi-ticker buy-setup scan of the
-- diversified watchlist (see backend/dashboard/scan.py). Written by the publish
-- job with the secret key; READ by the anon frontend (the 🔭 自选扫描 tab), so it
-- needs an anon SELECT policy (unlike predictions/source_weights which are
-- backend-only). `data` = {generated_at, tickers, results:[...]}.
create table if not exists public.watchlist_scan (
  id         text primary key,
  updated_at timestamptz not null default now(),
  data       jsonb not null
);

alter table public.watchlist_scan enable row level security;

drop policy if exists "anon read watchlist_scan" on public.watchlist_scan;
create policy "anon read watchlist_scan"
  on public.watchlist_scan for select
  to anon, authenticated
  using (true);

-- ── finra_short ──────────────────────────────────────────────────────────────
-- Single row (id='current') holding the FINRA daily short-volume cache (was the
-- local-only data/cache/finra_short_qbts.parquet). Persisted so the squeeze
-- "short" component survives stateless cloud (Lambda) runs — /tmp is wiped each
-- cold start and the cache was only ever refreshed in the local mining path, so
-- without this the cloud shows "短仓数据缺失". Backend-only: restored/refreshed/
-- pushed with the secret key by the publish job; NOT exposed to the anon frontend.
-- `data` = [{date, short_vol, total_vol, short_ratio}, ...].
create table if not exists public.finra_short (
  id         text primary key,
  updated_at timestamptz not null default now(),
  data       jsonb not null
);
alter table public.finra_short enable row level security;
-- No anon policy: only the secret-key backend touches this table.

-- ── watchlist + scan_journal (🔭 自选扫描 v1.1) ───────────────────────────────
-- watchlist:     single row 'current', data={tickers:[...]} — the editable list the
--                scan covers. scan_journal: single row 'current', data={records:[...]}
--                — every day's per-ticker call, graded after 5 trading days so the
--                scan is falsifiable. Both backend-only (secret key); the anon
--                frontend gets what it needs from the watchlist_scan payload.
create table if not exists public.watchlist (
  id text primary key, updated_at timestamptz not null default now(), data jsonb not null
);
alter table public.watchlist enable row level security;

create table if not exists public.scan_journal (
  id text primary key, updated_at timestamptz not null default now(), data jsonb not null
);
alter table public.scan_journal enable row level security;

-- scan_paper: single row 'current', data={positions:{...}, closed:[...]} — a
-- $1000-per-buy-signal paper-trading ledger (backend/dashboard/scan_store.py),
-- held until a sell signal so we can show realized P&L. Backend-only (secret key);
-- the anon frontend gets the summary from the watchlist_scan payload.
create table if not exists public.scan_paper (
  id text primary key, updated_at timestamptz not null default now(), data jsonb not null
);
alter table public.scan_paper enable row level security;

-- ── dca_state (📥 定投专区) ───────────────────────────────────────────────────
-- Single row 'current' holding the DCA seasonality read for the broad ETFs
-- (backend/dashboard/dca.py). Written by the publish job (secret key), READ by the
-- anon frontend (the 定投专区 tab) → needs an anon SELECT policy.
create table if not exists public.dca_state (
  id text primary key, updated_at timestamptz not null default now(), data jsonb not null
);
alter table public.dca_state enable row level security;
drop policy if exists "anon read dca_state" on public.dca_state;
create policy "anon read dca_state" on public.dca_state
  for select to anon, authenticated using (true);

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
