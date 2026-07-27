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
