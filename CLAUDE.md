# CLAUDE.md — QBTS Quant Lab

Instructions for any Claude session working in this repo. Auto-loaded every session.

## ⚠️ Multi-session coordination (READ FIRST)

Several Claude sessions may run at once. Sessions are isolated — they do **not**
see each other's context. Coordinate through files + git:

1. **Before starting work, read [COORDINATION.md](COORDINATION.md)** to see what other
   sessions are doing and which files they've claimed.
2. **Append an entry** to COORDINATION.md: timestamp, a one-line task description, and the
   files/areas you're about to touch. Mark it `[done]` when finished.
3. **Never edit a file another active session has claimed.** If you need it, pick a
   different slice or note the handoff in COORDINATION.md.
4. **Two sessions must never edit the same working directory at the same time** — disk is
   last-write-wins, and git state will collide. For genuine parallel work, give each
   session its own git worktree + branch:
   ```bash
   git worktree add ../qbts-<task> -b <task>
   ```
   Then coordinate via commits / `git log` / PRs, not the shared tree.
5. **Commit small and often** so other sessions/worktrees can see your work. Push to
   `main` **only when the user asks** — `main` triggers the deploy workflows.

## What this is

Personal one-screen trading dashboard for **QBTS** (D-Wave Quantum), traded via leveraged
ETFs **QBTX** (2× long) / **QBTZ** (2× short). Daily it answers: buy QBTX / buy QBTZ / hold,
with an executable trade plan (entry/stop/target/RR/size), key drivers, and catalysts.

## Architecture

- **backend/** — FastAPI (`backend/api.py`): builds the dashboard snapshot, runs classic +
  mined factor strategies, SMC, macro, journal, and the AI decision.
- **backend/dashboard/decision.py** — THE brain: one **Opus 4.8** (`claude-opus-4-8`) call →
  trade-plan JSON. (Was `claude-fable-5` until Fable was disabled.)
- **publish.py** — full pipeline + fresh decision → writes Supabase (`dashboard_state` +
  `factors`). The deployed site reads Supabase, so the site only updates when this runs.
- **quote_pusher.py** — live pre/post quotes → Supabase `live_quote` (`--once` = single push).
- **frontend/** — Next.js 16 static export on GitHub Pages, reads Supabase.
  **Read [frontend/AGENTS.md](frontend/AGENTS.md) — Next 16 has breaking changes.**
- **Supabase** — the data store the deployed site reads (`dashboard_state`, `factors`, `live_quote`).
- **aws/** — Route A serverless: container-image Lambdas. `PublishFunction` (Function URL +
  daily 09:00 ET schedule) and `QuoteFunction` (every minute, market hours). See `aws/README.md`.

## Run locally

- `./start.sh` → backend :8000 + frontend :3000. `./stop.sh` to stop.
- The dashboard reads **Supabase** when `NEXT_PUBLIC_SUPABASE_URL` is set (it is, in
  `frontend/.env.local`). So to change what the site shows, run `publish.py` — the local
  backend's own data is only the fallback.
- The dashboard's **控制台** buttons (local mode) run publish / toggle the quote pusher
  against the local backend (`/control/*` endpoints in `api.py`).

## Deploy (all from `main`)

- **Frontend**: push touching `frontend/**` → Pages workflow auto-deploys.
- **AWS**: push touching `backend/**` / `publish.py` / `quote_pusher.py` / `aws/**` →
  "Deploy AWS jobs" auto-runs (also manual). Backend/prompt changes need this redeploy to
  reach the cloud image.
- End commit messages with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` line.

## Gotchas

- **Lambda FS is read-only except `/tmp`** — the image symlinks `backend/data/cache` →
  `/tmp/cache` and the handler pre-creates it (dangling-symlink `mkdir` raises otherwise).
- **`aws/requirements.txt` is the full dep set** for the image (repo `requirements.txt` is
  incomplete — `lightgbm` needs `libgomp`, installed via `dnf` in the Dockerfile).
- **`dashboard_snapshot(force_refresh=True)` propagates to `load_or_fetch`** so `as_of`
  stays current. **yfinance `end` is EXCLUSIVE** — `fetch_daily`/`fetch_hourly` use
  `end=today+1d` so the current (live partial) or just-closed session is included; with a
  bare `end=today` an AEST user (ahead of US) sees `as_of` a session stale until UTC
  midnight. During a live US session `as_of` is the current date with a *partial* daily bar.
- **Secrets**: `ANTHROPIC_API_KEY` / `SUPABASE_SECRET_KEY` / `ALPACA_*` live in root `.env`
  (gitignored). Supabase **secret** key (`sb_secret_…`) is write-capable — local/CI only;
  the **publishable** key is safe-public read-only. Repo is public.
- **Models**: Opus 4.8 (decision) · Sonnet 4.6 (factor gen) · Haiku 4.5 (news / reflections).
- **Big image push to ECR occasionally times out** in CI — just re-run "Deploy AWS jobs".

## Lessons learned (append new ones here)

Mistakes worth not repeating — when you learn one, add a dated bullet here.

- **2026-06-24 · Verify market facts live, never from training memory.** I claimed
  "SpaceX is private / can't be bought"; it had IPO'd as **NASDAQ: SPCX** after my
  knowledge cutoff. For ANY current market fact (is X listed? its ticker / price /
  sector? a recent IPO / rename / split — e.g. Marathon→MARA Holdings?), verify with
  a tool first (repo `yfinance`: `yf.Ticker(t).info` for longName/price; or WebSearch).
  The dashboard's numbers are already computed from live fetched data — only off-hand
  factual claims I make from memory risk being stale.

- **2026-06-24 · For ANY stock/market topic, lead with WebSearch (+ `yfinance`), never
  memory** *(user's standing instruction)*. When a question touches a specific stock —
  lockups / IPO terms / float / catalysts / earnings dates / valuation / "how low can it
  go" / "is X a buy" — do live research **first** (WebSearch for events, schedules, news;
  repo `yfinance` for price / float / fundamentals), then answer. Never give a number or a
  fundamental claim from training memory; cite sources. Two corollaries:
  - **Don't name a precise top/bottom** — give anchored *scenarios* (IPO price, 52w
    range, valuation comps), and say plainly that exact levels aren't knowable.
  - **The watchlist scan is purely mechanical (SMC / volume / regime) and BLIND to
    events** (lockup unlocks, earnings, dilution). Never present a scan "buy level" as
    safe without the event/supply backdrop — e.g. it flagged SPCX "回踩 $148 可买" off
    only ~7 days of post-IPO data, right at the all-time low and right before a ~2×-float
    lockup unlock. Mechanical levels need a live-research sanity check for fresh IPOs /
    event-driven names.

## Surfaces & standing decisions (as of 2026-06-25)

Frontend tabs (`frontend/app/`): **🎯 决策仪表盘** (`/`) · **🔭 自选扫描** (`/watch`) ·
**📥 定投专区** (`/dca`) · **🏆 因子排行榜** (`/factors`).

- **自选扫描 (`scan.py` / `scan_store.py`)** — mechanical multi-name buy-setup scan
  (SMC/volume/regime + trend/RSI), ~$0 (one Haiku commentary). Carries: a **$1000-per-
  buy-signal paper-trading ledger** (`scan_paper` table; buy on 买入区, sell on 偏空回避 /
  到目标 / 跌破均线, 0.2%/side cost), **exit hints**, a static **lockup countdown**
  (`LOCKUPS` dict, SPCX), **earnings overlay**, a **thin-data guard** (<60 bars → flagged
  & excluded from paper trades), **market context** (SPY/QQQ vs 50dMA + VIX risk-on/off),
  and a **concurrent-buy correlation** note. Basket: QBTS POET EOSE RUN LUNR MARA AG NVDA
  SPCX MP SYM (editable from the site). Buy = 买入区 only; signals score the same way for all.
- **定投专区 (`dca.py`)** — REBUILT 2026-06-24 into a global **valuation menu**:
  **VTI / VEA / VWO / AVUV** (deliberately NOT VOO/QQQ/VTI/IOO — those are 4 flavors of
  expensive US). **Do not revert to dip-timing or a US-only set.** Locked-in philosophy
  (agreed with the user): time-in-market > timing; CAPE tilts across **regions, not US
  sectors**; from real SPY/QQQ/IOO drawdown→fwd-return data — only a **−20%+ capitulation**
  justifies deploying the reserve, **−5~10% above the 200dMA is the best return+win-rate
  blend**, the **−10~20% middle is the worst** ("falling knife", NOT a bargain), and
  buying near highs is fine. Cards show P/E + earnings-yield (CAPE proxy), target weights
  40/30/20/10, a ballast note (BND/SGOV), and a "keep separate from the QBTS speculation
  sleeve" warning. Macro CAPE (US ~40 / global ~27.7) is hardcoded with a "re-verify" note.

- **Measurement phase (important).** The scan paper-trade, decision journal, and
  calibration only *just* started logging — **signals are statistically UNPROVEN**. A UI
  gate warns until ≥30 graded calls. Standing guidance given to the user: **don't size up
  real money until the track record shows an edge.** Treat the whole thing as a measurement
  tool for now; the next optimization should be driven by the accumulated results.
- **All Supabase migrations have been run** (decision_journal, calibration/predictions/
  source_weights, watchlist, scan_journal, finra_short, watchlist_scan, scan_paper,
  dca_state). Running cost ≈ **$20/mo**, almost all of it the one daily Opus decision at
  **09:00 ET** (≈ 23:00 Melbourne in AU winter / 01:00 in AU summer).

## Durable facts vs this file

`CLAUDE.md` = conventions/orientation. Cross-session **durable facts** go in the project
memory (`memory/MEMORY.md`), which every session loads at startup.
