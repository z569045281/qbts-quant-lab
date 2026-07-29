# 行情数据 / 取数口径

> 读这份文件的时机:动 `data/fetcher.py`、`quote_pusher.py`、时间戳/`as_of`/夜盘/缓存。

## yfinance 口径

- **`dashboard_snapshot(force_refresh=True)` propagates to `load_or_fetch`** so `as_of`
  stays current。
- **yfinance `end` is EXCLUSIVE** — `fetch_daily`/`fetch_hourly` 用 `end=today+1d`,
  这样当日(实时部分 bar)或刚收盘的那根才会被包含;写成裸 `end=today` 的话,AEST 用户
  (领先美国)会看到 `as_of` 卡在上一交易日直到 UTC 午夜。During a live US session `as_of`
  is the current date with a *partial* daily bar。
- **15m bars**:`data/fetcher.py::load_15m`(独立 `QBTS_15m.parquet` 缓存,不动
  `(1h,1d)` 的 `load_or_fetch` 元组契约);yfinance 15m 只给 ~60 天;失败返回 `None`
  → 上层降级(playbook 显示 "trigger unavailable")。
- 盘前 yfinance 会给一根 `close=NaN` 的当日占位 bar,静默传染下游字段(2026-07-16 /dca
  全空事故)——聚合前先 `dropna`。

## 🌙 夜盘(Blue Ocean overnight,`quote_pusher.py::fetch_overnight`, 2026-07-22)

yfinance 的 `prepost` 只覆盖到盘后 20:00 ET,**夜盘(20:00–04:00 ET)yfinance 全盲**——
用户在 moomoo 夜盘下单时仪表盘曾整段变黑。补法用**已部署的 `ALPACA_*` key** + Alpaca 数据 API
的 **`feed=overnight`**(免费档即可拿实时 Blue Ocean 成交/盘口;`feed=sip`/`feed=boats`
都 403 需订阅,不用它俩)。

- `build_payload` 仅在 `us_session()==closed` 且 `_overnight_window()`(Sun–Thu 20:00+ /
  Mon–Fri 00:00–03:59)时才打 Alpaca,以 QBTS 最新 mark ≤20min 判定夜盘活跃
  (否则假日夜/周六退回昨收)→ `session="overnight"`。
- **价格取 bid/ask 中点、不是最后成交**:夜盘薄,成交稀疏,QBTZ 实测印过 19h 前的 $6.49
  陈价,而其 live 盘口中点 $5.83 才对(=2× 反推的 implied 也是 5.84)。
- 调度补窗见 [AWS-LAMBDA.md](AWS-LAMBDA.md)(`OvernightEvening` / `OvernightMorning`)。
- **夜盘价只做展示,不驱动信号**(薄流动性 UNPROVEN);`challenge2` 已自门控在
  09:30–16:00,夜盘不会误交易。前端 `SESSION_BADGE.overnight`「🌙 夜盘」徽章 +
  `LiveQuoteEntry` 加 `ov_age_s/ov_bid/ov_ask/ov_trade`。

## 杠杆 ETF 公允价

QBTX/QBTZ 盘中显示**隐含公允价 + 折溢价**(quote_pusher),决策的失效价换算锚也用公允价
(`decision._anchor_prices`),不用可能陈旧的最后成交价。

## 时区

所有对用户可见的时间戳走 ET(新闻曾误用 UTC);持仓天数按 ET 日期算(UTC 会虚高一天,
直接影响 1-3 天军规判定)。用户在墨尔本(AEST/AEDT)。

## 坏 bar 守卫(2026-07-29)

上游偶发返回违反 OHLC 不变式的行(`low ≤ min(open,close) ≤ max(open,close) ≤ high`)。
实例:yfinance 把 QBTS **07-24 的收盘 16.21 贴进 07-28 那行**,而该行 low 是 17.26 ——
收盘低于当日最低价,数学上不可能(真实收盘 17.64,30m 末根 / 盘后报价 / Alpaca 夜盘盘口三方一致)。

`fetcher.py` 两层处理:

1. `_bad_ohlcv_rows()` —— 不变式**只此一处定义**,零误报(两天收同价是合法的,收盘掉出
   当日区间不是)。命中即剔除,并记进 `LAST_FETCH_ISSUES`(**不许只写日志**)。
2. **as_of 不许倒退** —— 剔掉的若是最新那根,as_of 会无声退回前一天。所以新抓的最后
   一根比缓存还旧时,把缓存里多出来的补回去:缓存里的 bar 是写入时通过同一套不变式的,
   比"没有"可信。

出口:`snapshot['data_health'] = {ok, issues}` → 决策页黄条。**坏数据被拦下这件事本身
必须可见**,否则页面照常正常,没人知道少了一天。
