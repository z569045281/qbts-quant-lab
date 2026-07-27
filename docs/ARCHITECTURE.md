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
