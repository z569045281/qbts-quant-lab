# Supabase 表与迁移

> 读这份文件的时机:新增表、改写库逻辑、"页面空白/写入静默失败"。

部署站点只读 Supabase;本地后端的数据只是 fallback。写库靠 `SUPABASE_SECRET_KEY`
(见 [SECRETS.md](SECRETS.md))。

## 主要表

| 表 | 写入方 | 内容 |
|---|---|---|
| `dashboard_state` | `publish.py` | 每日全快照(永久累积,可回测) |
| `factors` | `publish.py` | 因子/策略排行 |
| `live_quote` | QuoteFunction / `quote_pusher.py` | 实时报价 + `data.smc` / `data.geo` 等盘中重算结果 |
| `decision_journal` | `journal.py` | 决策台账(含 HOLD 判读、影子表态) |
| `predictions` / `source_weights` | `calibration.py` | 逐源预测与学习权重 |
| `watchlist` / `watchlist_scan` / `scan_journal` / `scan_paper` | `scan*.py` | 自选扫描 + 纸面账本 |
| `finra_short` | `squeeze.py` | 空量比历史 |
| `dca_state` | `dca.py` | 定投状态 |
| `crypto_challenge` | `challenge2.py` | 千元挑战(`id='current'`;round 1 归档在 `'round1-2026-07'`) |
| `guerrilla_state` | `guerrilla.py` | 游击战仓位/流水/冷却 epoch |
| `spacex_state` | `spacex.py` | SpaceX 第二仪表盘(`id='current'`) |
| `publish_audit` | `aws/lambda_handlers.py::_audit_click` | 真人点击审计 |

## 迁移状态

**All migrations have been run** — **except 这三个,待用户在 Supabase 控制台跑**:

- `sql/publish_audit_migration.sql`(2026-07-09,点击审计表)
- `sql/spacex_migration.sql`(2026-07-13;没跑之前 /spacex 显示建表提示、每日 publish 的
  SpaceX 写入静默失败但不崩)
- `sql/guerrilla_migration.sql`(2026-07-22,anon 读策略;表缺 = /factors 不渲染该卡)

**约定**:新表必须做到「表不存在也不崩」——写入 best-effort,前端缺表就不渲染。
