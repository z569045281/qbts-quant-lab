# AWS Lambda / 定时调度

> 读这份文件的时机:改 `aws/**`、加盘中任务、动 EventBridge cron、云端行为与本地不一致。

两个 Lambda 共用一个容器镜像:`PublishFunction`(Function URL + 每日 09:00 ET)与
`QuoteFunction`(每分钟,行情窗口内)。全景见 `aws/README.md`。

## 已知陷阱(每条都是踩出来的)

- **Lambda FS is read-only except `/tmp`** — the image symlinks `backend/data/cache` →
  `/tmp/cache` and the handler pre-creates it (dangling-symlink `mkdir` raises otherwise)。
- **`aws/requirements.txt` is the full dep set** for the image(repo `requirements.txt` is
  incomplete — `lightgbm` needs `libgomp`, installed via `dnf` in the Dockerfile)。
- **sys.path trap**:`quote_handler` imports `dashboard.*` directly, but `backend/` is only
  added to `sys.path` as a side-effect of importing `backend.api` (api.py line ~22) — which
  the quote path never does. So `lambda_handlers.py` inserts `$LAMBDA_TASK_ROOT/backend` on
  `sys.path` at module load; without it `from dashboard…` raises `ModuleNotFoundError`
  (这正是盘中 SMC 区块一直没落地的那个 bug)。
- **调试不用 CloudWatch**:`live_quote.data['smc_err']` 只在失败时写入,直接从 Supabase 看。
- QuoteFunction 已提到 **1024MB / 90s**(盘中 pandas 重算)。

## QuoteFunction 分钟槽位表(加新任务前先看这里,别撞车)

| 槽位 | 任务 | 说明 |
|---|---|---|
| `minute % 5 == 0` | SMC playbook 盘中重算 | pre/regular/post,off-minute 结转不闪烁 |
| `minute % 15 == 2` | 千元挑战 bot(`challenge2`) | 偏移 2 分躲开 `%5` |
| `minute % 30 == 8` | 地缘雷达 `maybe_geo_refresh` | 躲开 `%5` 与 `%15==2` |
| `minute % 5 == 4` | 游击战 `check_exits` | 只在有 open 仓时才拉 1m 行情 |
| 16:05–20:00 ET 每日一次 | 游击战信号自算 / 特调收盘推送 | `meta.last_compute_date` 去重 |
| 周日 20:0x ET | 周末 BTC 信号 + 补一发周末地缘检查 | 分钟错开 `%5` |

## EventBridge 调度

- 常规:`cron(* 4-19 ? * MON-FRI *)` ET —— 04:00–19:59 盘前/盘中/盘后。
- 夜盘补窗(2026-07-22):`OvernightEvening` `cron(* 20-23 ? * MON-THU *)` +
  `OvernightMorning` `cron(* 0-3 ? * MON-FRI *)` —— 否则 20:00–04:00 ET 整段没人跑,
  用户在 moomoo 夜盘下单时仪表盘全黑。见 [MARKET-DATA.md](MARKET-DATA.md)。
- 周日晚:`SundayNightBtc` `cron(1/10 20-23 ? * SUN)` ET。
- 每日 09:00 ET:`PublishFunction`(全量 publish + 决策)。
- **周日 20:05 ET:`SundayNightDecision`**(2026-07-29)—— 周一那份决策提前到夜盘开门。
  09:00 ET 只比开盘早 30 分钟,而夜盘那时已跑 13.5 小时,周末跳空全在用户拿到决策之前
  (2026-07-26 实例:夜盘 +3.2% 走完才轮到 23:00 墨尔本的决策)。`:05` 是等
  `SundayNightBtc` 20:01 那条 `live_quote` 落库 + BTC 周日 UTC 线定案。
  **必须锚 ET**:墨尔本 10 月初进夏令时、纽约 11 月初才退,锚墨尔本 10:00 会从 10 月起
  提前到 19:00/18:00 ET,那时 `weekend_signal()` 返回 `None`(实测 19:55 ET → None)。
  台账不重复:`log_prediction` 按 `as_of` 去重,与周一 09:00 那份同为上周五那根日线。

## 点击审计

Lambda `_audit_click` 把每次**真人按钮点击**(出决策/自选/持仓)的 IP/UA/设备提示写进
`publish_audit`(cron 不记;失败不挡动作)。前端版本号连点 3 次开隐藏查看窗(audit-modal)。
浏览器拿不到计算机名——IP + 系统/浏览器 + 时区就是全部口径。表迁移见 [SUPABASE.md](SUPABASE.md)。
