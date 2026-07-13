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
- **backend/dashboard/decision.py** — THE brain: one **Fable 5** (`claude-fable-5`) call →
  trade-plan JSON, with **auto-fallback to Opus 4.8** on any primary failure (`decision.model`
  records who actually answered — Fable was disabled for us once, publish must survive that).
  The same call returns `system_notes`(AI 每日自检:数据问题/改进建议 → 仪表盘「AI 系统自检」卡).
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
- **每次 push 里只要含 `frontend/**` 的可见变更,必须同步升 `frontend/public/version.json`**
  (feature → 次版本 1.x,小修/补漏 → 1.x.y)。这是版本守卫提示用户刷新的唯一依据——
  不升版本,已打开的页面永远不知道有新构建(用户明确要求,2026-07-03)。

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
- **`ADANOS_API_KEY`** (optional, `sk_live_…`, in root `.env` + GitHub Actions secret +
  `template.yaml` `AdanosApiKey` → `deploy-aws.yml`): retail Reddit **buzz + sentiment** via
  `backend/data/altdata.py::fetch_adanos_sentiment` (Adanos free tier, 250 req/mo; register
  at adanos.org/register). **Replaced the dead Reddit signal** — Reddit's own API is
  approval-gated + bans AI use since 2026-06, and keyless StockTwits/Reddit `.json` are
  403-blocked (see memory [[reddit-api-dead]]). Wired into `snapshot['sentiment']`, the edge
  meta-model (`_SENTIMENT_WEIGHT=0.12`, low — retail sentiment is weak/laggy) and the decision
  prompt. Blank key → signal simply off (degrades cleanly). Endpoint returns top-level
  `buzz_score`/`sentiment_score`/`trend`/`bullish_pct`/`bearish_pct`; `X-API-Key` header.
- **千元挑战第二期 bot** (`backend/dashboard/challenge2.py`, runs inside QuoteFunction at
  `minute%15==2` market-hours ticks — offset dodges the `%5` SMC minutes): $5000 paper
  sleeve on **Alpaca paper** (real orders, REST via `requests` — alpaca-py is NOT in the
  Lambda image on purpose). Entry = `challenge_basket` 全场之选 (87% market + GTC bracket
  TP+11.5%/STOP−12%), +10% touch = liquidate (触碰即落袋; bracket is only the backstop).
  **🏁 马拉松模式 (2026-07-10 用户改规则)**: 不再 +10% 判赢收手 — $5500 只是里程碑
  (首次报喜一次), 持续交易到 **2026-08-15**; 落袋当日冷却次日再进场 (否则下一跳原价
  买回白付点差); floor $4250 硬性停手不变; 每跳记 `equity_curve` (15min 粒度, cap
  2000 点) → /challenge 页 SVG 资金曲线。State = Supabase `crypto_challenge` id='current'
  (round 1 archived at 'round1-2026-07'); frontend /challenge renders it dynamically.
  **`ALPACA_API_KEY`/`ALPACA_SECRET_KEY`** live in root `.env` + GitHub Actions secrets +
  `template.yaml` (`AlpacaApiKey`/`AlpacaSecretKey`, blank = bot off). ⚠️ Round-1 lesson:
  a plain market sell gets REJECTED while bracket children hold the shares — always exit
  via `DELETE /v2/positions/{sym}?cancel_orders=true` (round 1's "LIQUIDATE" never actually
  filled; stray position was cleaned 2026-07-08).
- **Models**: Fable 5 (decision, fallback Opus 4.8) · Sonnet 4.6 (factor gen) · Haiku 4.5 (news / reflections).
- **`DEEPSEEK_API_KEY`** (optional, root `.env` + GitHub Actions secret + `template.yaml`
  `DeepSeekApiKey` → `deploy-aws.yml`): **DeepSeek V4 Pro 影子决策**
  (`decision.py::generate_shadow_decision`, 2026-07-13) — 同一份 prompt 每天跑一遍
  DeepSeek(`deepseek-v4-pro`, api.deepseek.com, ~$0.02/天),挂在主决策 `shadow_ds`
  字段随缓存/payload 走。**零决策权**:不推送、不驱动交易、不进 edge;决策卡可
  Fable/DeepSeek 切换(v2.14.0),journal 顺带记 `ds_bold_call` 与 Fable `bold_call_5d`
  同一套 fwd5 口径评分(`audit.py` ② 🥊 表态vs5日两行同框)→ **8/15 影子考场宣判,
  赢了才谈换岗**。Blank key = 影子全关,主决策零影响。方向单 <5 bar 提前触发评分的
  日子 fwd5 无数据,该日两模型表态不计分(方向单稀有,可忽略)。
- **🚀 SpaceX (SPCX) 第二仪表盘** (`backend/dashboard/spacex.py`, 2026-07-13 用户要求):
  **决策只由 DeepSeek 生成、绝不回退 Fable**(与影子决策共用 `DEEPSEEK_API_KEY`,但这是
  一台**独立**的机器,不是影子)。SPCX 是普通个股 → 自包含:自抓 yfinance 技术读数 +
  Google News RSS 头条 + 硬编码事件日历,自己的 SPCX 专用 prompt(动作空间 **BUY/HOLD/
  REDUCE**,非 QBTX/QBTZ),`generate_spacex_decision` POST api.deepseek.com(json_object)→
  `_sanitize`(夹信心/补 RR/剔离谱位)。**无 key 或失败 → decision=None**(前端显示"待生成",
  不调 Claude)。接进 `publish.py` §4.7(每日 09:00 ET 云端 publish 刷新,DEEPSEEK_API_KEY
  已在该 Lambda env),写 Supabase **`spacex_state`**(id='current')。前端 `/spacex` +
  nav 🚀 标签 + `getSpacexState`。⚠️ SPCX 是**新 IPO**(~20 根日线):`thin_data` 标记 →
  prompt 显式让模型忽略 RSI/均线绝对值、以事件+价格结构为准;**2026-08-06 首次财报+首次
  锁定期解禁(~20% 内部人)**是 `_CATALYSTS` 里点名的压倒性风险(日期/比例需复核,`catalyst_asof`)。
  **待跑迁移 `sql/spacex_migration.sql`**(见下)。本地 `.env` 无 DeepSeek key → 本地 publish
  的 SPCX 决策必为 None,只有云端能生成。**单独重跑按钮**(v2.15.1):/spacex 页 🔄 按钮 →
  `postSpacexRefresh` POST `action:"spacex"` 到 Function URL(云)/ `/scan/watch`(本地)→
  `publish_handler` 与 api.py 各有 `spacex` 分支跑 `publish_spacex()`(~30-60s,DeepSeek 推理);
  云端每日 publish(`_publish_decision_only`)也已带上 SpaceX,和 scan/dca 一样 best-effort。
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
  **Refinements (2026-07-01)**: premium/discount is anchored to the **dealing range of the
  swing that printed the last structure label** (`_dealing_range`: down-break → top = the LH
  just before the break, bottom = lowest low since), NOT the global hi/lo (which inflated the
  0.5 line). The entry is forced **≤ $1.00 wide** — drilled to the tightest 1h/4h FVG∩OB
  confluence inside the relay zone (clipped to the proximal edge as a last resort), so a wide
  daily OB never tanks the RR. The stop hugs the **refined entry** (not the HTF zone). And a
  **risk circuit-breaker** (`rr_veto`): if RR < 2.0 the entry is invalid → state forced to
  观望 (`risk_note` rendered amber on the card). TP1 is measured **beyond the entry edge** so an
  FVG overlapping the entry can't masquerade as the target and trigger a false veto.
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
- **🌍 地缘政治/政策雷达** (`backend/dashboard/geopolitics.py`): QBTS 与伊朗战局/川普
  政策强联动(07-07 暴跌=谈判破裂),机械信号对此全盲 — 此模块补盲区。三条 track
  (伊朗/中东、川普政策、量子政策)走 **Google News RSS search**(免费无 key,`when:2d`
  窗口),一次 **Haiku** 调用做逐条 relevance/stance/中文注 + 整体 risk_level
  (alert/watch/calm)。成本闸:RSS 免费随便拉,Haiku 只在头条集合变化或分析 >6h 才跑。
  接进 snapshot(`payload['geopolitics']`)+ 决策 prompt(alert 时明示降信心/缩仓)。
  **盘中**: quote_handler 在 `minute%30==8`(错开 %5 SMC、%15==2 挑战 bot)调
  `maybe_geo_refresh` → 写 `live_quote.data['geo']`(off-tick carry-forward),
  **新高影响条目 / 风险级别翻转 → ntfy 推送**(去重靠 payload 里的 `alerted` key 列表;
  首次运行不推防轰炸;周日 20:01 ET 那跳顺带补一发周末局势检查)。**推送频控
  (2026-07-10,一晚 20 条轰炸后加)**:级别升级立推(high);同级别持续报道 3h 冷却、
  降级 1h 冷却(冷却中新条目静默登记,卡片照常盘中更新);`last_push_ts` 随
  live_quote 携带。前端决策页
  优先读 live 版(`live?.geo ?? snap.geopolitics`),alert 整卡变红。无新增 secret
  (复用 ANTHROPIC_API_KEY + NTFY_TOPIC,均已在 template.yaml Globals)。

## Strategy research archive

**[mining.md](mining.md)** — 2026-07 三轮 47 套策略回测的完整档案:收益 DNA、最终排行、
**已判死家族清单**(经典指标独立系统/折价买溢价卖/做空暴涨/日内隔夜翻仓/N=3 swing 等)。
再测策略前先读它;判死的家族没有新证据不得重提(同 qbts-range-trading-no-edge 待遇)。

## Lessons learned (append new ones here)

Mistakes worth not repeating — when you learn one, add a dated bullet here.

- **2026-06-24 · Verify market facts live, never from training memory.** I claimed
  "SpaceX is private / can't be bought"; it had IPO'd as **NASDAQ: SPCX** after my
  knowledge cutoff. For ANY current market fact (is X listed? its ticker / price /
  sector? a recent IPO / rename / split — e.g. Marathon→MARA Holdings?), verify with
  a tool first (repo `yfinance`: `yf.Ticker(t).info` for longName/price; or WebSearch).
  The dashboard's numbers are already computed from live fetched data — only off-hand
  factual claims I make from memory risk being stale.

- **2026-07-07 · Never gate prompt/signal readouts behind a ledger's "new daily bar"
  idempotence.** The 09:00 ET publish runs *premarket*, so `today` = the previous session's
  date; after a holiday weekend there is no new bar for days → any `last_date != today`
  update block silently skips → on Monday 07-06 the decision prompt lost ALL first-tier
  readouts (BTC/QTUM/IONQ z40/CLV/特调 all null) exactly when 周末BTC定周一 mattered most
  (the AI self-check caught it). Ledger *accounting* must stay once-per-bar idempotent, but
  *readouts* are pure functions of current data — compute them fresh on every call
  (`analyze_champs` now returns them in a `today` block). Corollary: a signal that only
  rides ntfy/live_quote (btc_weekend was) is invisible to the decision — wire it into the
  snapshot too.

- **2026-07-13 · A static/slow variable must never masquerade as a daily direction
  signal.** Dashboard audit found the 13F source fired on 18/19 graded days with the
  single largest average push in the edge model (+0.26 log-odds, always bullish) while
  hitting 18% (n=17) — the same quarterly filing re-emitted daily as if it were fresh
  news, single-handedly dragging edge overall to 25% direction hit in a downtrend. Fixes
  (`holdings.py`): staleness gate keyed to the **active holders'** report date (the
  all-holders max gets whitewashed by monthly-reporting mutual funds) — ≤75d full
  strength, 75–120d linear fade, >120d muted (display untouched); plus "vanguard"/"geode"
  added to passive keywords (Vanguard Portfolio/Capital Management arms were counted as
  active "new positions" = fake smart-money votes). Same audit: HOLD decisions are now
  gradeable in `audit.py` (|decision-day QBTS| < 3% = correct, preregistered 2026-07-13)
  so the journal accumulates a record even when the AI stays out (was 20 HOLD / 21 days
  = zero judgeable samples), and nav paper-horses report vs same-window buy&hold
  (`bh_ret_pct` — they had "all losses" optics while actually ALL beating B&H by
  4–11pp). Known open issue: `python audit.py` crashes on GBK Windows consoles
  (UnicodeEncodeError on ⚖) — run with `PYTHONIOENCODING=utf-8` (user declined the fix
  for now).

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
  buy-signal paper-trading ledger** (`scan_paper` table; buy on 买入区 **only when the tape
  isn't risk_off**, sell on a **volatility-scaled stop fixed at entry** (≈2× daily vol, clamped
  6–14% — `_stop_pct`) / 偏空回避 / 到目标, 0.2%/side cost. **2026-07-01 fix**: the old sim
  reused the soft UI "跌破20/50线" `exit_hint` as a hard stop, so a 买入区 (needs close>20MA but
  can sit <50MA) was flagged 'risk' and stopped the SAME day it opened → every trade a 1-day
  whipsaw loss. Now the stop is its own entry-anchored level and entries are tape-gated; the
  ledger was reset once on this change. **2026-07-13 机制 v2**(首月战绩买入区 0/6、
  账本 −$226 后六连修): ①目标过 **1.5R 盈亏比门**(沿参照列表向上取第一个 ≥1.5×止损
  距离的,都不够=不设目标 `target_rr_veto`) ②模拟器改 **回踩限价挂单**(照卡片打法挂
  需求区上沿,5 交易日内触价按 min(open,limit) 成交,过期/转空撤单;现价已在买点才即时
  进场) ③买入区改 **顺风×回踩合取**(pts≥3 且 趋势腿 且 位置腿,缺腿降级) ④**板块
  轮动门**(`SECTOR_OF` 映射到 sector_rotation 象限,左半边降级) ⑤无目标仓位 **破10日
  线跟踪出场** ⑥`avoid` 避雷块(偏空回避=首月唯一 66% 命中的信号)。新单 epoch='v2',
  v1 老仓按新出场规则跑完,审判按 epoch 分开统计。), **exit hints**, a static **lockup countdown**
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
  buying near highs is fine. Cards show P/E + earnings-yield (CAPE proxy), a "keep
  separate from the QBTS speculation sleeve" warning. Macro CAPE (US ~40 / global ~27.7)
  is hardcoded with a "re-verify" note. **2026-07-13 (user: "都加") menu completed into a
  full portfolio**: equity tier **+AVDV** (international small value, AVUV's mirror) at
  weights 30/20/14/8/8 = 80%, plus a **ballast tier** (`BALLAST_META`) **BND 12% +
  GLDM 8%** with own cards + weights (`ballast_etfs` in payload) → total 100%. Ballast
  deploy is overridden to 固定比例·不择时 — the equity drawdown→deploy evidence does NOT
  apply to bonds/gold (GLDM sat −24% off its Jan-2026 $5,595/oz high at add-time, which
  the equity rules would falsely read as 深跌可加码).

- **Measurement phase (important).** The scan paper-trade, decision journal, and
  calibration only *just* started logging — **signals are statistically UNPROVEN**. A UI
  gate warns until ≥30 graded calls. Standing guidance given to the user: **don't size up
  real money until the track record shows an edge.** Treat the whole thing as a measurement
  tool for now; the next optimization should be driven by the accumulated results.
- **⏰ REMINDER — re-derive the edge weights once calibration has samples.** Every weight in
  `edge.py` is a **hardcoded prior, not derived from data**: `_MINED_WEIGHT_PER_SHARPE=0.8`,
  `_CLASSIC_WEIGHT_BASE={high:0.40,medium:0.20,low:0.08}`, `_NEWS_WEIGHT=0.15`,
  `_REL_STRENGTH_WEIGHT=0.20` (relative-strength, added 2026-07-02 — picked to match the
  medium-classic tier, **no empirical basis**). They only self-correct via
  `_learn_mult(src)` (load_learned_weights), which stays 1.0 until a source has enough graded
  predictions. **When the calibration/journal record crosses ~30 graded calls per source,
  tell the user and re-derive these weights (and each source's keep/drop) from the real
  hit-rate table — don't keep trusting the hand-tuned priors.** Until then treat every edge
  p_up as an unvalidated guess. (User explicitly asked to be reminded of this.)
  **审判执行器已就位(2026-07-09): `python audit.py`** — 汇总校准逐源命中+决策台账+
  纸面马+扫描账本,按预注册规则(n≥30 且 Wilson95% 下界>0.5 转正 / 上界<0.5 剔除)
  出判决报告(backend/dashboard/audit.py;只读,权重改动仍走人工 review)。8/15 直接跑它。
- **All Supabase migrations have been run** (decision_journal, calibration/predictions/
  source_weights, watchlist, scan_journal, finra_short, watchlist_scan, scan_paper,
  dca_state) — **except `sql/publish_audit_migration.sql`(2026-07-09 点击审计表,待用户跑)
  和 `sql/spacex_migration.sql`(2026-07-13 SpaceX 第二仪表盘 `spacex_state` 表,待用户跑;
  没跑之前 /spacex 显示建表提示、每日 publish 的 SpaceX 写入静默失败但不崩)**。
  点击审计:Lambda `_audit_click` 把每次真人按钮点击(出决策/自选/持仓)的 IP/UA/
  设备提示写进 `publish_audit`(cron 不记,失败不挡动作);前端版本号连点 3 次开
  隐藏查看窗(audit-modal)。浏览器拿不到计算机名——IP+系统/浏览器+时区就是全部口径。 Running cost ≈ **$20/mo**, almost all of it the one daily Opus decision at
  **09:00 ET** (≈ 23:00 Melbourne in AU winter / 01:00 in AU summer).

## Durable facts vs this file

`CLAUDE.md` = conventions/orientation. Cross-session **durable facts** go in the project
memory (`memory/MEMORY.md`), which every session loads at startup.
