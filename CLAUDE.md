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
  the **publishable** key is safe-public read-only. Repo is public. **Both `.env` AND
  `.env.example` are gitignored** — document new secrets here / in `aws/README.md`, not just
  in `.env.example`.
- **`FRED_API_KEY`** (optional, in root `.env` + GitHub Actions secret + `template.yaml`):
  backfills the macro calendar's **actual** values via `backend/dashboard/fred.py`. The FF
  feed only carries forecast/previous — never actual. Without the key the calendar still
  works (actual blank). The cloud daily-publish Lambda needs it too, so it's wired through
  `aws/template.yaml` (`FredApiKey`) + `deploy-aws.yml`.
- **Models**: Opus 4.8 (decision) · Sonnet 4.6 (factor gen) · Haiku 4.5 (news / reflections).
- **Big image push to ECR occasionally times out** in CI — just re-run "Deploy AWS jobs".
- **Nadaraya-Watson 包络** (`backend/dashboard/nadaraya_watson.py::analyze_nw_envelope`):
  non-repainting Gaussian-kernel mean-reversion band (causal one-sided kernel — does
  NOT peek at the future like LuxAlgo's default two-sided version, so its win rate is
  the honest, tradeable one, not the inflated repainting backtest). Faithful port of the
  user's Pine v5 strategy "NWE Mean Reversion [魔改 v4]" — same endpoint algo, bands, and
  trigger lines. `level=90` → buy_line at bottom 10% of the band (their yellow line, price
  ≤ it = buy, +1 to scan score), sell_line at top 10% (orange line, ≥ it = fade, −1);
  `crossed_in/out` flag the exact crossunder/crossover bar. Wired into the scan score (±1, same
  magnitude as RSI so it can't dominate) + card (`nw` block, note) and the QBTS decision
  prompt (`snapshot['nw_envelope']`, framed as a mean-reversion entry-timing/take-profit
  reference, not a standalone direction). Gets graded by the paper-trade ledger like every
  other signal — treat its edge as UNPROVEN until the record shows one.
- **SEC dilution overlay** (`backend/data/altdata.py::fetch_sec_dilution`): free EDGAR
  (`data.sec.gov`), no key — flags recent 424B* (实际增发/high) & S-3/S-1 (货架/warn) per
  ticker. Wired into the scan (badge on every 自选 card) and the QBTS decision prompt. **SEC
  requires an email-shaped `User-Agent` or it 403s** — default is a fake-domain UA (like FINRA);
  override with `SEC_USER_AGENT` if ever needed. No Supabase table (rides watchlist_scan + live
  decision fetch). This is the event-aware backstop for the otherwise event-blind mechanical scan.
- **SMC 顺势纪律 Playbook** (`backend/dashboard/smc.py::build_playbook`, attached as
  `smc['playbook']`; **QBTS decision page only**, 自选扫描 still uses the legacy `analyze_smc`
  fields untouched). Three-module disciplined state machine on top of the base SMC read:
  **① 全局方向锁** = read ONLY from the *latest* daily structure label (`last_event.dir`,
  BOS **or** CHoCH) → `lock` bull/bear/none; bull = longs-only (回踩), bear = shorts-only
  (诱多). **② 降维中继状态机**: `WAIT → ARMED → TRIGGER`. ARMED = price in discount(bull)/
  premium(bear) past the fib-0.5 equilibrium **AND** touching a sub-TF (4h-resampled-from-1h
  or 1h) relay order block. TRIGGER (AND logic) = ARMED **AND** a fresh 15m same-direction
  **CHoCH** **AND** a close-confirmed **VMC dot**. **③ FVG**: entry = FVG∩OB overlap
  (共振狙击点); TP1 = nearest unfilled FVG near-edge ahead (止盈磁吸); TP2 = range extreme.
  Output carries a 5-item ✓/✗ checklist + entry/stop/TP1/TP2/RR — the UI renders it as the
  card's top block and `decision.py` frames it as the **整体评判标准** (overrides scattered
  signals). **VMC green/red dot is replicated** via `backend/dashboard/wavetrend.py`
  (LazyBear WaveTrend — VMC/Cipher-B is just WT crossing out of oversold/overbought) since
  VMC itself is a closed TradingView script — treat it as a faithful *approximation*, not
  pixel-identical. **15m bars**: new `data/fetcher.py::load_15m` (separate `QBTS_15m.parquet`
  cache so the `(1h,1d)` `load_or_fetch` tuple contract is untouched; yfinance 15m caps at
  ~60d; returns `None` on failure → playbook degrades to "trigger unavailable"). Like every
  other signal it's UNPROVEN until the paper-trade/journal record shows an edge.
- **SMC playbook 盘中刷新 + TRIGGER 推送** (`backend/dashboard/intraday_smc.py`,
  wired in `aws/lambda_handlers.py::quote_handler`). The daily 09:00 publish computes
  the playbook **once** — but its TRIGGER (15m CHoCH + VMC dot) is fleeting & intraday,
  so a once-a-day compute can never catch it. Fix: the **per-minute QuoteFunction**
  (`cron(* 4-19 ... ET)`) recomputes the *cheap* playbook (cached daily/1h + **fresh
  15m** only; no LLM → ~$0) **~every 5 min** (`now_et.minute % 5 == 0`, pre/regular/post),
  writes it into `live_quote.data['smc']`, and **carries it forward** on the off-minutes so
  it doesn't flicker. The frontend (`page.tsx`) **prefers the live playbook** over the daily
  snapshot's (`live?.smc?.playbook ?? snap.smc?.playbook`) + shows a「盘中实时」pulse.
  **Push**: an `ntfy.sh` POST fires on the **rising edge** into TRIGGER only (dedup via the
  previous state read back from `live_quote`). Set **`NTFY_TOPIC`** (root `.env` + GitHub
  Actions secret + `template.yaml` `NtfyTopic` param → `deploy-aws.yml`); blank = no push
  (playbook still refreshes + shows). `NTFY_URL` optional (default `https://ntfy.sh`). Title
  stays ASCII (HTTP header is latin-1); Chinese detail goes in the UTF-8 body. QuoteFunction
  bumped to 1024MB / 90s for the pandas recompute. Subscribe to the topic in the ntfy phone app.
  **Lambda sys.path trap**: `quote_handler` imports `dashboard.*` directly, but `backend/` is
  only added to `sys.path` as a side-effect of importing `backend.api` (api.py line ~22) — which
  the quote path never does. So `lambda_handlers.py` now inserts `$LAMBDA_TASK_ROOT/backend` on
  `sys.path` at module load; without it `from dashboard…` raises `ModuleNotFoundError` (was the
  bug that kept the intraday block from ever landing). `live_quote.data['smc_err']` surfaces any
  recompute exception (only set on failure) so you can debug from Supabase without CloudWatch.

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
  (SMC/volume/regime + trend/RSI + **NW 包络**), ~$0 (one Haiku commentary). Carries: a **$1000-per-
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
