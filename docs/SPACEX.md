# 🚀 SpaceX (SPCX) 第二仪表盘

> 读这份文件的时机:改 `backend/dashboard/spacex.py` 或 `/spacex` 页。

`backend/dashboard/spacex.py`(2026-07-13 用户要求)。**决策只由 DeepSeek 生成、绝不回退 Fable**
——与影子决策共用 `DEEPSEEK_API_KEY`,但这是一台**独立**的机器,不是影子。

## 结构

SPCX 是普通个股 → 自包含:自抓 yfinance 技术读数 + Google News RSS 头条 + 硬编码事件日历,
自己的 SPCX 专用 prompt(动作空间 **BUY/HOLD/REDUCE**,不是 QBTX/QBTZ)。
`generate_spacex_decision` POST api.deepseek.com(json_object)→ `_sanitize`(夹信心/补 RR/
剔离谱位)。**无 key 或失败 → decision=None**(前端显示"待生成",**不调 Claude**)。

接进 `publish.py` §4.7(每日 09:00 ET 云端 publish 刷新,`DEEPSEEK_API_KEY` 已在该 Lambda env),
写 Supabase **`spacex_state`**(id='current')。前端 `/spacex` + nav 🚀 标签 + `getSpacexState`。
**单独重跑按钮**(v2.15.1):/spacex 页 🔄 → `postSpacexRefresh` POST `action:"spacex"` 到
Function URL(云)/ `/scan/watch`(本地)→ `publish_handler` 与 api.py 各有 `spacex` 分支跑
`publish_spacex()`(~30-60s,DeepSeek 推理);云端每日 publish(`_publish_decision_only`)
也带上 SpaceX,和 scan/dca 一样 best-effort。

⚠️ 本地 `.env` 无 DeepSeek key → 本地 publish 的 SPCX 决策必为 None,只有云端能生成。
⚠️ 待跑迁移 `sql/spacex_migration.sql`,见 [SUPABASE.md](SUPABASE.md)。

## 薄数据(新 IPO)

SPCX 只有 ~20 根日线:`thin_data` 标记 → prompt 显式让模型**忽略 RSI/均线绝对值**、
以事件 + 价格结构为准。**2026-08-06 首次财报 + 首次锁定期解禁(~20% 内部人)**是 `_CATALYSTS`
里点名的压倒性风险(日期/比例需复核,见 `catalyst_asof`)。

## 抢先量三条腿(v2.16.0,用户:"三条腿都加")

新 IPO 日线只 ~20 根、指标失真,这三条都**不吃日线历史长度**,全 best-effort(None 不阻断),
均喂进 DeepSeek prompt:

1. **期权隐含波动 `fetch_spacex_options`**(前瞻·零历史):ATM 跨式 → 预期波动%,IV 期限结构,
   事件到期(≥`_EVENT_DATE` 2026-08-06)溢价,~10% OTM 看跌−看涨 IV 偏斜。
   实测近月 ±6.5%、8/07 到期 ±17.7%(市场已给解禁+财报定价)。
2. **盘中 1h `fetch_spacex_intraday`**:同 20 个交易日但 ~130 根 1h bar,RSI/ATR/均线/锚定VWAP
   全预热可用 —— 杀手锏对比:日线 RSI 73(失真)vs 盘中 RSI ~27(可信)。
3. **同业波动先验 `fetch_spacex_peer_prior`**:`_PEERS`(RKLB/ASTS/LUNR 纯太空 + PLTR 对照 + ARKX)
   一年历史,收缩估计 `blended = w·自算 + (1−w)·同业中位`,`w = n/(n+_SHRINK_K=60)`
   (20 根 → w≈0.24,主要借同业)。

前端 /spacex 三个彩色区块 + data.ts 类型。**IV 预测幅度不预测方向**;仍无法 front-run
8/6 解禁供给(**事件永远第一优先**)。

## 战绩台账(2026-09-02,用户问「战绩如何」问出来的)

**上线到 2026-09-02 的 50 天里,这台机器一条记录都没留下。** `spacex_state` 只有
一行 `id='current'` 每天被整块覆盖,`decision_journal` 是 QBTS 专用的 ——
「它是不是天天都说 HOLD」这种最基本的问题都答不出来。

`backend/dashboard/spacex_journal.py` 补上:

- **存哪**:复用 `spacex_state` 表,一条决策一行 `id='j:YYYY-MM-DD'`。
  **故意不建新表** —— 仓里已经有个 `sql/spacex_migration.sql` 等着跑,
  再加一个迁移就是再加一个「代码上线了但库没建好」的哑火窗口。
  无凭据退回本地 JSONL(同 journal.py)。
- **口径**:与主台账 `journal.py` 对齐,不另立标准。BUY 看目标/止损谁先到、
  都没到看第 5 个交易日收益;REDUCE 镜像;**HOLD 不进准确率**,只记 5 日收益 +
  `|收益| ≥ 3%` 标 miss(同 `audit.py` 的 `_HOLD_MISS_PCT`)。
  同根 bar 内目标止损都触及 → 判 loss(日线看不出先后)。
- **预注册判决线**:方向性样本 <20 一律 UNPROVEN;够 20 条后看 Wilson 95% 下界是否 >50%。
- 接进 `publish_spacex()`(`_journal_step`,best-effort,台账炸了不拖垮 publish),
  战绩写进 payload 的 `scorecard` 字段 → 前端 /spacex 「📒 战绩台账」区块。
- 历史**无法回填**(从来没存过)。已用 `current` 里那条真实的 08-31 决策播了种。

## 期权 IV 事故(2026-09-02 同批修)

**每日 publish 跑在 09:00 ET,期权市场 09:30 才开** → 抓到的链里
yfinance 的 `impliedVolatility` 是没刷新的垃圾。09-01 存进库的是
`atm_iv` 0.0039 / 0.002 / 0.002 / 0.002(盘后重抓同样四个到期是 48–54%)。两条下游后果:

1. DeepSeek 拿 0.0039→0.002 写出「IV 期限结构上升显示未来波动加大」—— 方向读反,对废数字编故事。
2. 偏斜段只要求 `pv>0 and cv>0`,两个垃圾值都过闸 → `skew=0.0`,渲染成「下行担忧不重」。
   **假的安心比没有更糟。**

修法:
- `_sane_iv` 范围闸(5%–500%),链上值不在区间一律判坏数据 —— ATM IV 与偏斜共用。
- 坏了就用 **`_iv_from_straddle`(Brenner–Subrahmanyam 闭式,σ=跨式/(0.8·S·√T))** 兜底。
  跨式价来自真成交报价,陈旧但真实(这正是 `expected_move_pct` 一直没坏的原因)。
  实测反解 vs 链上:0.5332/0.53、0.4768/0.48、0.4678/0.49。
  **故意不用 brentq** —— 只解 ATM 一个点却把 scipy 拖进 Lambda 依赖不值得。
- 新字段 `iv_source`(chain/straddle)、`iv_slope`(远月−近月 IV)、`iv_degraded`。
- 提示词点死陷阱:**预期波动随 √T 必然变大,它上升不构成任何信号**;期限结构只看 IV 差。
  偏斜取不到时显式说「不代表为零」。
- 顺手:`event_expiry` 只在事件**未发生**时才给(硬编码的 8/6 早过了,原来永远返回近月,
  提示词照旧写「市场已给 8/6 事件定价」);事件日历渲染加【已发生·N天前】/【还有N天】标记。
