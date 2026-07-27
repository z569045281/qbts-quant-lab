# 教训档案(踩过的坑,别再踩)

> 读这份文件的时机:**改任何"标签/开关/窗口/提示词规则"之前**,以及回答任何市场事实问题之前。
> 学到新教训就在这里加一条带日期的 bullet(最新在上)。

## 一句话版(元规则,先扫这个)

| 元规则 | 出处 |
|---|---|
| 任何股票/市场事实,先 WebSearch + yfinance,永不凭记忆 | 2026-06-24 ×2 |
| 读数的显示名必须和产出它的公式对得上,否则它会理直气壮说反话 | 2026-07-28 |
| 加了可选入参"提升精度",必须 grep 生产路径确认真有人传 | 2026-07-28 |
| 加了版本/代际标签,必须同一个改动里 grep 所有读取方 —— 没人过滤的标签只是装饰 | 2026-07-22 |
| 提示词里的数值规则不会自执行,护栏要落在代码里 | 2026-07-22 |
| 滚动窗口截断的地图不许把"看不见"说成"不存在" | 2026-07-20 |
| 静态/慢变量不得冒充每日方向信号 | 2026-07-13 |
| 读数不得被"新 bar 才更新"的幂等逻辑挡住(账目才需要幂等) | 2026-07-07 |
| 一起渲染的字段要做**交叉一致**检查,不只逐字段查空 | 记忆 [[review-cross-source-consistency]] |

---

- **2026-07-28 · 一个读数的「名字」和「产出它的公式」必须对得上,否则它会理直气壮地
  说反话;同理,一个没人填的入参等于没有这个功能。** AI 自检 07-28 报了四条,查下来
  三条真、且其中两条是同一个病的两种形态:**①名不副实** —— `intraday.py` 的
  `surge_ratio = 末60分钟量量 / 当日自身每分钟均速`,被显示成「量比 0.9×(正常区间)」。
  它按当日自我归一化,**结构上不可能看见日级别放量**:07-27 QBTS 全天 2.62× 天量
  (4716万 vs 20日均量 1801万),它照样输出 0.93 并盖章"正常"。修:显示口径改成
  「末60分 X× 当日均速」,另加真·量比 `day_vol_ratio`(当日/前20日均量)。
  **②入参没人填** —— `api.py` 里 `analyze_smc/volume_profile/intrabar` 都接受
  `live_price`,注释写着"so zones are measured against reality, not yesterday's close",
  但它的来源 `_LIVE_QUOTE_CACHE` **只有本地 `/quote/live` 端点会写**;云端 publish 从不
  走那条路,且 `refresh_decision` 里 `dashboard_snapshot()` 本来就排在 `quote_live()`
  **之前** → 线上 `_live_px` 恒为 None,这些模块一直吃的是收盘价。于是暴涨日出现两个
  「今天」:派生读数说"折价区3%/快%R −97.9",实时价其实已 +18.5%。**③守卫自己误报** ——
  `selfcheck.py` 那条"价格段 vs 量能段差>2pp=快照不同步"的确定性规则,比的是 as_of 日线
  bar 的涨跌 vs **当前 session** 的涨跌,两者在日线缓存落后时本就是不同的两天,于是
  07-27 稳定误报;已改成只在 `intraday.session == as_of 的 MM-DD` 时才判矛盾。
  **处置(用户拍板接通)**:`_live_price_for_snapshot()` 在进程内缓存拿不到时回读 Supabase
  `live_quote`(quote_pusher 每分钟在写),超过 20 分钟的陈价一律退回 None 用收盘价——
  **陈价注进 SMC/POC 比收盘价更糟,因为它会假装自己是"现在"**。`analyze_nw_envelope`
  加 `live_price` 参数,但**只替换位置判定,带子仍由收盘构建**:拿盘中价重跑核回归
  会让包络在自己脚下移动(repainting),而这个移植版存在的意义就是不重绘。决策 prompt
  的 `_price_basis_note` 相应把读数分成「已用实时价」和「仍是收盘口径」两类分别交代。
  ⚠️ 这改变了 8/15 受审信号(SMC playbook 还驱动 ntfy TRIGGER)的输入,审判时样本横跨
  两套口径,分代看。
  **推论:凡是给读数起中文名/显示名的地方,回头核一遍公式算的到底是不是那个东西;凡是
  加了可选入参来"提升精度"的地方,grep 一遍生产路径上到底有没有人传它。** 与
  2026-07-22「没人读的标签只是装饰」同宗。

- **2026-07-22 · A "分代记账" tag written at log time is worthless until something
  actually reads it at grading time.** `calibration.py::log_prediction` started
  tagging `model:"v2"` on 2026-07-17 with the comment "校准/审判按代际分开" — but
  `grade_predictions()` never once checked that field; it graded all 27 logged
  predictions (24 dead v1 + 3 live v2) as one blended pool. The AI self-check cited
  "25条23%命中率" as if it were v2's live track record and suggested flipping the
  model to inverse-weighted NOW instead of waiting for 8/15 — that number was
  **100% v1's already-known 21% zombie data**; the true v2 sample was 1 gradable
  prediction (partial horizon), nowhere near a real track record. Fixed by making
  `grade_predictions(model="v2")` the default (filters `r.get("model","v1")`),
  with the v1 legacy stat kept visible in `audit.py`'s report for context, not
  blended into the live judgment. **Corollary: whenever you add a generation/version
  tag to stop old data from contaminating a metric, grep every reader of that data
  store in the same change — a tag nobody filters on is decoration, not a fix.**
  Also caught same session: `smc.py::find_sweeps`'s note text embedded only the
  OLD swept swing-level's date ("扫过 03-25 高点…"), never the recent date the
  sweep itself occurred on — technically correct (the event date field was right)
  but an easy misread as "this old level is a current reference." Fixed by
  prefixing the sweep's own event date in the note string.

- **2026-07-22 · Prose risk guidance in an LLM prompt is not self-enforcing —
  a numeric rule needs a code-level guardrail, not just a sentence.** User
  challenged why the decision journal was 20/21 days HOLD while QBTZ ran
  $3.54→$6.81 (+92%, 06-15→07-17). Traced the one real attempt (06-25
  SHORT_QBTZ, conviction 6): `regime.py` had already classified that exact day
  as `expansion` (87th ATR percentile) and its `stop_hint` text — sitting right
  in that day's prompt — said stops need "≥1.5×ATR". The model's actual numeric
  stop came in at only ~1.03×ATR ($2.65 vs ATR14=$2.58), got whipsawed out 2
  days later (−10.45%) on a bounce that only reached $24.26, then QBTS fell all
  the way to the $18.66 target anyway — a 1.5×ATR stop ($25.42) would have
  survived the whipsaw and turned a losing trade into a winner. Fixed in
  `decision.py::_sanitize_decision`: after the model returns entry/stop/target,
  compute the regime-implied floor (`1.5×ATR14` if `regime=="expansion"` else
  `1.0×ATR14`, using that day's real `atr_pct`×price) and widen the stop in code
  if the model's number is tighter than the floor — verified against the exact
  06-25 numbers plus synthetic already-wide/normal-regime-too-tight cases.
  **Corollary: any time a prompt tells the model "your number must satisfy rule
  X," check whether X is actually enforced afterward — if it's just descriptive
  text, the model can and will ignore it under pressure (a fat R:R, a confident
  thesis), and the fix belongs in code, not in stronger wording.**

- **2026-07-20 · 滚动窗口截断的地图不得宣称"某侧无参照"——这是第二次栽在同一类
  bug 上。** 07-13 SMC `find_order_blocks` 只扫 `[-4:]` 丢了 5/19 需求 OB;07-20
  volume_profile 的 naked-POC 60 日窗把 3-4 月 $13-14.5 需求带(全 2 年 45.8% 的成交
  在 $15 下)整体挡在窗外,卡片对用户说"下方真空"——两次都是用户拿 TradingView 对比
  才暴露。原则:**结构性记忆(未回补 OB/naked POC/Strong Low)只因"被回补"而失效,
  不因"太老"而失效**;滚动窗口只该用于需要灵敏可破的读数(价值区/趋势),不该用于
  "找最近的下方参照"这类会因窗口空转而输出假否定的查询。新增此类地图时先问:
  窗口截断时它会不会把"看不见"说成"不存在"。

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

- **2026-06-24 · Verify market facts live, never from training memory.** I claimed
  "SpaceX is private / can't be bought"; it had IPO'd as **NASDAQ: SPCX** after my
  knowledge cutoff. For ANY current market fact (is X listed? its ticker / price /
  sector? a recent IPO / rename / split — e.g. Marathon→MARA Holdings?), verify with
  a tool first (repo `yfinance`: `yf.Ticker(t).info` for longName/price; or WebSearch).
  The dashboard's numbers are already computed from live fetched data — only off-hand
  factual claims I make from memory risk being stale.
