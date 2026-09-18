# 架构与本地运行

> 读这份文件的时机:第一次进这个仓库、要改数据流向、要搞清楚"哪个文件干什么"。

## 这是什么

Personal one-screen trading dashboard for **QBTS** (D-Wave Quantum), traded via leveraged
ETFs **QBTX** (2× long) / **QBTZ** (2× short). Daily it answers: buy QBTX / buy QBTZ / hold,
with an executable trade plan (entry/stop/target/RR/size), key drivers, and catalysts.

## 模块地图

- **backend/** — FastAPI (`backend/api.py`): builds the dashboard snapshot, runs classic +
  mined factor strategies, SMC, macro, journal, and the AI decision.
- **backend/dashboard/decision.py** — THE brain(详见 [DECISION.md](DECISION.md))。
- **publish.py** — full pipeline + fresh decision → writes Supabase (`dashboard_state` +
  `factors`). The deployed site reads Supabase, so **the site only updates when this runs**.
- **quote_pusher.py** — live pre/post/夜盘 quotes → Supabase `live_quote`
  (`--once` = single push)。详见 [MARKET-DATA.md](MARKET-DATA.md)。
- **frontend/** — Next.js 16 static export on GitHub Pages, reads Supabase.
  **改前端前必读 [../frontend/AGENTS.md](../frontend/AGENTS.md) — Next 16 has breaking changes.**
- **Supabase** — the data store the deployed site reads。表清单见 [SUPABASE.md](SUPABASE.md)。
- **aws/** — Route A serverless: container-image Lambdas. `PublishFunction` (Function URL +
  daily 09:00 ET schedule) and `QuoteFunction` (every minute, market hours)。
  See `aws/README.md` + [AWS-LAMBDA.md](AWS-LAMBDA.md)。

## 数据流(一句话)

```
yfinance/EDGAR/FRED/RSS/Alpaca → backend snapshot → decision.py(LLM) → publish.py
   → Supabase(dashboard_state / factors / live_quote / …) → GitHub Pages 前端
```

盘中另有一条便宜的旁路:QuoteFunction 每分钟跑,按分钟槽位重算 SMC playbook / 挑战 bot /
地缘雷达 / 游击战,写进 `live_quote.data`,前端优先读 live 版。槽位表见 [AWS-LAMBDA.md](AWS-LAMBDA.md)。

## 本地运行

- `./start.sh` → backend :8000 + frontend :3000. `./stop.sh` to stop.
- The dashboard reads **Supabase** when `NEXT_PUBLIC_SUPABASE_URL` is set (it is, in
  `frontend/.env.local`). So to change what the site shows, run `publish.py` — the local
  backend's own data is only the fallback.
- The dashboard's **控制台** buttons (local mode) run publish / toggle the quote pusher
  against the local backend (`/control/*` endpoints in `api.py`).
- 本地 `.env` 无 DeepSeek key → 本地 publish 的 SPCX 决策必为 None,只有云端能生成。

## 前端页面(标签)

`frontend/app/`:**🎯 决策仪表盘** (`/`) · **🔭 自选扫描** (`/watch`) · **📥 定投专区** (`/dca`) ·
**🏆 因子/策略战绩** (`/factors`) · **🏁 千元挑战** (`/challenge`) · **🚀 SpaceX** (`/spacex`)。
各页的产品决策与不可回退的约定见 [SURFACES.md](SURFACES.md)。

## 成本

Running cost ≈ **$20/mo**, almost all of it the one daily decision call at **09:00 ET**
(≈ 23:00 Melbourne in AU winter / 01:00 in AU summer)。DeepSeek 影子 ~$0.02/天;
盘中重算全是本地 pandas(~$0);Haiku 新闻/反思/地缘按需。

## ✂️ 已删除模块(2026-09-18 系统瘦身,用户拍板)

依据是同日的决策台账全量回测(78 条 → 56 份独立决策)与推送台账。代码已从 `main` 删除,
**git 历史可找回;Supabase 里的历史表/行一律未动**。别在没有新证据时把它们加回来。

| 删掉的 | 为什么 | 连带删掉 |
|---|---|---|
| 地缘雷达 `geopolitics.py` | 推送 239 条里占 135 条(56%);第三十一轮定性后视镜,记分卡命中 0%;每 30 分钟调一次 Haiku | 决策 prompt 段、readings 行、champions 成员、lambda `%30==8` 槽位、主页卡片 |
| 机械元模型 `edge.py` + `calibration.py` | `p_up` 两代实测负相关(07-30 −0.41;09-18 v2 n=38 −0.21,喊 BUY 后 5 日 −4.6%、喊 SELL 后 +1.9%) | api 快照 `edge`、`predictions` 记账、学习权重、audit ①、月度复盘里的校准段、未被引用的 calibration-card |
| v1 反向影子 | 依赖 edge.py 的 v1;n 小且 5 日窗重叠,不能据此反着用 | journal `v1inv_*` 新字段、决策卡灰卡 |
| DeepSeek 影子决策 | 表态命中 44% vs 同比例瞎猜 58%;每天多一次付费调用 | journal `ds_*` 新字段、决策卡切换钮与对照卡(SpaceX 页的 DeepSeek 主模型**保留**) |
| 游击战 `guerrilla.py` | 上线以来 0 单触发,却每天收盘后拉数据计算 | lambda 槽位、audit ⑤、/factors 观察卡 |
| /mu 第二考场 `second_ticker.py` | 四个视界技巧值全负(5 日 50% vs 基线 64%),每天多一次 LLM | /mu 页面、导航、快照字段 |

经典策略摘除名单(`_REDUNDANT` / `_DEAD_SOURCE` / `_EVENT_DAY_MUTED`)原住 edge.py,已搬进 `decision.py` 顶部,
决策 prompt 照旧用它过滤。
