# 信号模块目录

> 读这份文件的时机:改任何一个信号模块、加新数据源、"这个卡片的数字哪来的"。
> SMC playbook 单独一份:[SMC-PLAYBOOK.md](SMC-PLAYBOOK.md)。策略回测档案:[../mining.md](../mining.md)。

**通用纪律**:新信号一律先当 **UNPROVEN**,接进展示 + 台账评分,不直接给决策权重;
判决走 8/15 审判([AUDIT-AND-EDGE.md](AUDIT-AND-EDGE.md))。

## Nadaraya-Watson 包络 `nadaraya_watson.py::analyze_nw_envelope`

Non-repainting 高斯核均值回归带(**因果单侧核** —— 不像 LuxAlgo 默认的双侧版偷看未来,
所以它的胜率是诚实可交易的那个,不是被重绘美化的回测)。忠实移植用户的 Pine v5 策略
"NWE Mean Reversion [魔改 v4]"。`level=90` → buy_line 在带的底部 10%(用户的黄线,
价格 ≤ 它 = 买,扫描 +1 分),sell_line 在顶部 10%(橙线,≥ 它 = 减,−1);
`crossed_in/out` 标出精确的穿越 bar。接进扫描分(±1,与 RSI 同量级,不让它主导)+ 卡片
(`nw` 区块)+ QBTS 决策 prompt(`snapshot['nw_envelope']`,框成**均值回归的进场择时/止盈参考**,
不是独立方向)。
⚠️ mining.md 第十二轮:**实时贴下轨 = 刀还在落**(妖股上是负 alpha 入场点);
它在**指数/杠杆 ETF** 上才是主场(适用域研究)。

## 🌍 地缘政治/政策雷达 `geopolitics.py`

QBTS 与伊朗战局/川普政策强联动(07-07 暴跌 = 谈判破裂),机械信号对此全盲 —— 此模块补盲区。
三条 track(伊朗/中东、川普政策、量子政策)走 **Google News RSS search**(免费无 key,
`when:2d` 窗口),一次 **Haiku** 调用做逐条 relevance/stance/中文注 + 整体 risk_level
(alert/watch/calm)。**成本闸**:RSS 免费随便拉,Haiku 只在头条集合变化或分析 >6h 才跑。
接进 snapshot(`payload['geopolitics']`)+ 决策 prompt(alert 时明示降信心/缩仓)。

**盘中**:quote_handler 在 `minute%30==8` 调 `maybe_geo_refresh` → 写 `live_quote.data['geo']`
(off-tick carry-forward),**新高影响条目 / 风险级别翻转 → ntfy 推送**(去重靠 payload 里的
`alerted` key 列表;首次运行不推防轰炸;周日 20:01 ET 那跳顺带补一发周末局势检查)。
**推送频控(2026-07-10,一晚 20 条轰炸后加)**:级别升级立推(high);同级别持续报道 3h 冷却、
降级 1h 冷却(冷却中新条目静默登记,卡片照常盘中更新);`last_push_ts` 随 live_quote 携带。
前端决策页优先读 live 版(`live?.geo ?? snap.geopolitics`),alert 整卡变红。无新增 secret。
> 定位(mining.md 第十四轮):**决策刹车 + 缓和触发器,不是 alpha 源**;日频 GPR 指数抓不到
> 07-07 这类文本事件,所以雷达本身不可回测,只能前向计量。

## SEC 数据(`backend/data/altdata.py`,免费 EDGAR,无 key)

- **增发叠加层 `fetch_sec_dilution`**:标记近期 424B*(实际增发/high)与 S-3/S-1(货架/warn)。
  接进扫描(每张自选卡的 badge)+ QBTS 决策 prompt。**SEC 要求 email 形状的 `User-Agent`
  否则 403** —— 默认用一个假域名 UA(像 FINRA),必要时用 `SEC_USER_AGENT` 覆盖。无 Supabase 表
  (搭 watchlist_scan + 决策实时拉取的车)。这是机械扫描(事件盲)的事件补盲后盾。
  > mining.md 第十七轮:424B **公告次日普遍回落**(去极端 −2.32%,t=−2.13,胜率 30%),
  > 可交易半径只有 1-2 天 —— badge 文案已覆盖"刚出 424B 别急着买"。
- **8-K 重大事件 `fetch_sec_events`**:item 解码 + 严重度分级 → snapshot extras + 决策 prompt。
  `_classify_301` 抓 filing 原文正文自动定性 item 3.01(自愿转板 info / 合规缺陷 high /
  判不出退回 warn)。⚠️ SEC 标准条目抬头本身含 "failure to satisfy"(所有 3.01 通用模板),
  **必须先剥抬头再匹配关键词**,否则自愿转板被误判 high。
- **内部人卖出 `fetch_insider_form4`**:只取本票 Form 4 非衍生 `code='S'`(公开市场卖出,
  排除 M 行权/A 授予)+ yfinance float 算占比。实测 QBTS 近 60 天 $35.4M / 占流通 0.57%
  —— 与新闻里"三票合计 $988M"观感天差地别,**遇多票聚合数字一律以本票口径为准**。

## 散户情绪 `fetch_adanos_sentiment`(需 `ADANOS_API_KEY`)

Adanos 免费档(250 req/mo,adanos.org/register)的 Reddit **buzz + sentiment**。
**替代已死的 Reddit 信号** —— Reddit 官方 API 自 2026-06 起审批制且禁止 AI 用途,
无 key 的 StockTwits/Reddit `.json` 一律 403(记忆 [[reddit-api-dead]])。
接进 `snapshot['sentiment']`、edge 元模型(`_SENTIMENT_WEIGHT=0.12`,低 —— 零售情绪弱且滞后)
和决策 prompt。空 key → 信号直接关闭(干净降级)。端点返回顶层
`buzz_score`/`sentiment_score`/`trend`/`bullish_pct`/`bearish_pct`;`X-API-Key` header。
> mining.md 第二十一轮独立佐证:搜索热度/注意力类数据在这票上天生是**价格的镜子**(同周
> corr +0.22~0.32,下周不显著),所以权重必须低。

## 🎯 极度超卖游击战 `guerrilla.py`(2026-07-22 用户点单)

**服务端收盘自算 + ntfy** 的高危观察模块(用户原提 TradingView webhook,后改口
"webhook 和 TV 都不需要,触发发 ntfy 就行" → 三条件全在服务端用现有数据自算,
**无 webhook / 无 TV / 无 secret**)。Bear Lock 下逆宏观、顺微观订单流的多头游击:

- **A** 日线 WaveTrend wt1 < −70(VMC/Cipher-B 核心线,实测 4.4% 天数达标)
- **B** 连续两日 Intrabar POC(15m 子 bar volume-at-price 重构,~26 根/日)重合 ≤ $0.05(停机坪)
- **C** RR ≥ 2.5(stop = POC 底座 −0.05,target = 上方最近历史 POC 墙 / 无则 50 日高)

`maybe_guerrilla_signal(now_et)` 在 QuoteFunction 里跑:**收盘后 16:05–20:00 ET 每日算一次**
(`meta.last_compute_date` 去重),命中 → ntfy + 开 $1000 纸面仓。出场 `check_exits`
(`minute%5==4`,只在有 open 仓时拉 1m 行情)触 stop/target → ledger → **武装 24h 冷却**
(冷却由平仓武装,epoch 存 Supabase,fail-CLOSED)。**零决策权**,/factors 直读 `guerrilla_state`。
ntfy 复用 `NTFY_TOPIC`。15m 重构比 Pine 的 5m 粗,$0.05 停机坪偏严可能长期静默 —— UNPROVEN,8/15 同审。

## ⏳「今天在等什么」卡 `waiting_for.py::build_waiting_card`

2026-07-22 用户:"天天观望,我都不知道在等什么"。六个一级扳机(特调抄底 / RSI2 超卖 /
同行落后追赶 / 周末BTC / 相对估值 z40 / crypto 顺风辅助腿)的当前读数 + 距触发距离,
纯展示复用 snapshot 现成读数(`champs.today`/`relative_strength`/`btc_weekend`/`market_light`),
**零新拉取、不进决策权重**。`api.py payload["waiting_for"]` → 决策页历史战绩卡上方。
HOLD 的真实含义 = 这六个扳机没扣(如"特调蹲守:收盘 ≥$18.16 即触发")。
⚠️ **阈值与 decision.py B 级清单一一对应,改扳机记得两处同步。**

## 其它接线中的读数

- **宏观 `macro.py`**:`_IMPACT_COEF` 影响系数表(mining.md 第十五轮实测:非农 SPY ×1.56*
  是数据日之王;**QBTS 单票在所有宏观日系数全 ≈1.0**,宏观走的是大盘/板块通道)+
  `_NUCLEAR_PATTERNS` 只留 非农/失业率/CPI/FOMC/JacksonHole;FOMC 的肉在**次日**(×1.31)。
  actual 值靠 `fred.py` 回填(需 `FRED_API_KEY`),`_ref_ok` 硬校验参考期防止上月值冒充实际。
- **`squeeze.py` 空头动向**:空量比 60 日 z 方向读数(z>1 偏空 / z<−1 顺风)。
  经典的"挤空燃料"叙事**已被判反**(mining.md 第五轮:QBTS 的空头是聪明钱),置信度封顶 medium,
  prompt 里明写"只当风向不当扳机"。
- **`regime.py`**:波动 regime + `stop_hint`;**expansion 下止损 ≥1.5×ATR 已在
  `decision.py` 代码里强制**(见 [DECISION.md](DECISION.md))。
- **`sector_rotation.py` 轮动地图 / `volume_profile.py` / `intrabar_profile.py`**:
  **地图非信号**(mining.md 第十七/二十六轮已判:象限做策略输在册马;裸 delta 阈值 t=1.2 判死)。
- **`selfcheck.py`**:全站六页自检(规则层 + Haiku 语义层)→ publish §4.8,回写 `site_check`。
  规则:**自证无矛盾一律不输出**(代码层 `_is_nonfinding` 兜底,不只靠 LLM 合规)。
