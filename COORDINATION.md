# COORDINATION — live worklog for concurrent Claude sessions

Shared scratchpad so parallel sessions don't collide. **Read this before you start;
append your entry; mark it `[done]` when finished.** See `CLAUDE.md` → Multi-session
coordination for the full rules.

Format (newest at top):

```
- [active] 2026-06-18 11:05 · <session/who> · <task> · files: <paths you're touching>
- [done]   2026-06-18 10:30 · <session/who> · <task> · files: <paths>
```

## Entries

<!-- add yours above this line -->

- [done] 2026-06-24 · scan-v1.1 · 自选扫描 A+B+C: A 网页加/删自选(Lambda action + 本地 /scan/watch) · B 扫描战绩(scan_journal,5日后评判命中率) · C AI 大白话点评(Haiku) · files: backend/dashboard/scan.py, backend/dashboard/scan_store.py(new), backend/api.py, aws/lambda_handlers.py, publish.py, supabase_schema.sql, frontend/app/watch/page.tsx, frontend/app/_lib/data.ts · 待用户在 Supabase 跑 scan_v11_migration.sql

- [done] 2026-06-24 · finra-short-fix · 修复挤空燃料"短仓数据缺失"(云端 /tmp 冷启动擦除+只在本地挖矿刷新): FINRA 短量缓存改 Supabase 持久化(finra_short 表),publish 前增量同步 · files: backend/data/altdata.py, publish.py, aws/lambda_handlers.py, supabase_schema.sql · 待用户在 Supabase 跑 finra_short_migration.sql

- [done] 2026-06-23 · watchlist-scan · 新「🔭 自选扫描」tab: 7只分散高波动篮子(QBTS/POET/EOSE/RUN/LUNR/MARA/AG)每日买点扫描,复用 SMC/成交量画像/regime,纯机械 · files: backend/dashboard/scan.py(new), publish.py, aws/lambda_handlers.py, supabase_schema.sql, frontend/app/watch/page.tsx(new), frontend/app/_components/nav.tsx, frontend/app/_lib/data.ts · 待用户在 Supabase 跑 watchlist_migration.sql

- [done] 2026-06-19 · review-followups · 5 改进: calibration→Supabase / 决策数字护栏 / ETF 价格确定性计算 / HOLD 影子评判 / 派生信号标注 · files: backend/dashboard/calibration.py, backend/dashboard/decision.py, backend/dashboard/journal.py, supabase_schema.sql, frontend/app/page.tsx, frontend/app/_lib/data.ts · 待用户在 Supabase 跑 calibration_migration.sql

- [done] 2026-06-18 · setup · created CLAUDE.md + this coordination worklog · files: CLAUDE.md, COORDINATION.md
