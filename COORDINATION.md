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

- [done] 2026-06-26 · choch-warn+plan-declutter · ①决策页加 CHoCH 早期反转预警横幅(snap.smc.last_event.kind==='CHoCH' 时显示,纯提示不发信号,补"等BOS确认所以进场晚"的空窗) ②交易计划卡精简:默认只显示 方向+QBTZ三价+盈亏比+仓位+失效条件,把 入场条件/波动档/QBTS镜像价/杠杆说明 收进 <details>展开看细节 · files: frontend/app/page.tsx · 注:page.tsx 同时有用户未提交的响应式 WIP,未替其提交

- [done] 2026-06-25 · et-melb-annot · 决策页 ET 时间旁加注墨尔本时间(保留ET): 实时报价(asof_epoch)+经济事件(ET挂钟 date+time_et) 显示「(墨 HH:MM)」,跨日补 MM-DD。format.ts 加 etMelbSuffix/epochMelbTime,经 IANA America/New_York→Australia/Melbourne 换算(自动处理两地夏令时)。AI 简报正文里的 ET 是自由文本,无法结构化转换,保持原样 · files: frontend/app/_lib/format.ts, frontend/app/page.tsx

- [done] 2026-06-25 · tz-local-render · 决策/简报/扫描时间戳显示成本地时区: 后端改输出带时区 UTC(datetime.now(timezone.utc)),前端新增 _lib/format.ts(parseUtc 把裸时间当 UTC + fmtLocalDateTime 用本地 getter 渲染),page.tsx/watch/page.tsx/brief-panel.tsx 改用之。顺带修了「决策时效」年龄被裸时间算错~10h 的 bug · files: backend/dashboard/{decision,brief,scan}.py, frontend/app/_lib/format.ts(new), frontend/app/page.tsx, frontend/app/watch/page.tsx, frontend/app/_components/brief-panel.tsx

- [done] 2026-06-25 · scan-paper-fix · 修模拟战绩把亏损单误标「到目标止盈」: ①_exit_hint 止损判定挪到止盈前(否则下跌后浮动目标塌到现价头顶,破位被误判止盈) ②scan 结果暴露 target_num ③run_paper_trades 止盈锚定入场当天目标(pos["target"]),不再用浮动目标 · files: backend/dashboard/scan.py, backend/dashboard/scan_store.py

<!-- add yours above this line -->

- [done] 2026-06-24 · dca-rebuild · 定投专区重做为「全球估值菜单」: 菜单换 VTI/VEA/VWO/AVUV(砍掉 4 只贵美股),每只显示 P/E+盈利收益率(粗估长期年化)+便宜/中性/偏贵;加「证据版何时多投」(深跌-20%+动预备金/小回调-5~10%在200线上方最优/中段-10~20%别抄底/近高点照投);宏观 CAPE 背景(美40/全球27.7)+建议配置(40/30/20/10)+压舱格(BND/SGOV)+与投机仓分开提示 · files: backend/dashboard/dca.py(重写), frontend/app/dca/page.tsx(重写), frontend/app/_lib/data.ts

- [done] 2026-06-24 · scan-hardening · 体检后修 P0/P1/P2: 数据不足守卫(<60天 thin_data,排除出纸面交易)、纸面交易扣0.2%/边成本、财报日历叠加(yfinance calendar,每卡倒计时)、大盘环境过滤(SPY/QQQ/VIX risk-on/off banner)、信号未验证门(已评判<30笔警告勿加仓)、组合相关性提醒(多买入信号合计相关性) · files: backend/dashboard/scan.py, backend/dashboard/scan_store.py, frontend/app/watch/page.tsx, frontend/app/_lib/data.ts

- [done] 2026-06-24 · scan-paper · 自选扫描加「模拟战绩」: 每个买入区信号模拟买入 $1000,持有到卖出信号(转空/到目标/跌破均线)平仓,记录已实现+浮动盈亏、胜率,前端面板展示 · 账本存 scan_paper 表(后端写,摘要随 watchlist_scan 给前端) · files: backend/dashboard/scan_store.py, backend/dashboard/scan.py, frontend/app/watch/page.tsx, frontend/app/_lib/data.ts, supabase_schema.sql · 待用户跑 scan_paper_migration.sql

- [done] 2026-06-24 · scan-add-mp-sym · 自选扫描新增 MP(稀土)+ SYM(机器人): 联网核实后选的两个低相关(0.45/0.41)高波动新驱动,补地缘/实体AI两条线;THEME 标签 + 加入 Supabase watchlist + 重扫(现 11 只) · files: backend/dashboard/scan.py(THEME) · 注: watchlist 存 Supabase,云端需 push 重部署才有 THEME 标签

- [done] 2026-06-24 · scan-lockup · SPCX 卡片加「下次解禁倒计时」: 静态解禁事件叠加层(LOCKUPS dict,日期来自联网核实),只展示不参与打分——补机械扫描看不见供给冲击的盲区;首次大解禁≈8/1(20%≈2倍流通盘) · files: backend/dashboard/scan.py, frontend/app/watch/page.tsx, frontend/app/_lib/data.ts

- [done] 2026-06-24 · scan-exit-hint · 自选扫描卡片加「轻量出场提示」(如有持仓): 按今日价 vs 上方目标/20·50日均线判定 → 🎯接近/已到目标(止盈) / ⚠️跌破均线(止损) / 👀测试支撑;无状态、不追踪成本 · files: backend/dashboard/scan.py, frontend/app/watch/page.tsx, frontend/app/_lib/data.ts

- [done] 2026-06-24 · dca-zone · 新「📥 定投专区」tab: 宽基 ETF(VOO/QQQ/VTI/IOO)定投季节性(万圣节/9月效应)+ 回调/200日均线 → 温和的加码/正常/偏高提示 · 另: CLAUDE.md 加「Lessons learned」段(verify-market-facts-live) · files: backend/dashboard/dca.py(new), publish.py, aws/lambda_handlers.py, supabase_schema.sql, frontend/app/dca/page.tsx(new), frontend/app/_components/nav.tsx, frontend/app/_lib/data.ts, CLAUDE.md · 待用户跑 dca_migration.sql

- [done] 2026-06-24 · scan-v1.1 · 自选扫描 A+B+C: A 网页加/删自选(Lambda action + 本地 /scan/watch) · B 扫描战绩(scan_journal,5日后评判命中率) · C AI 大白话点评(Haiku) · files: backend/dashboard/scan.py, backend/dashboard/scan_store.py(new), backend/api.py, aws/lambda_handlers.py, publish.py, supabase_schema.sql, frontend/app/watch/page.tsx, frontend/app/_lib/data.ts · 待用户在 Supabase 跑 scan_v11_migration.sql

- [done] 2026-06-24 · finra-short-fix · 修复挤空燃料"短仓数据缺失"(云端 /tmp 冷启动擦除+只在本地挖矿刷新): FINRA 短量缓存改 Supabase 持久化(finra_short 表),publish 前增量同步 · files: backend/data/altdata.py, publish.py, aws/lambda_handlers.py, supabase_schema.sql · 待用户在 Supabase 跑 finra_short_migration.sql

- [done] 2026-06-23 · watchlist-scan · 新「🔭 自选扫描」tab: 7只分散高波动篮子(QBTS/POET/EOSE/RUN/LUNR/MARA/AG)每日买点扫描,复用 SMC/成交量画像/regime,纯机械 · files: backend/dashboard/scan.py(new), publish.py, aws/lambda_handlers.py, supabase_schema.sql, frontend/app/watch/page.tsx(new), frontend/app/_components/nav.tsx, frontend/app/_lib/data.ts · 待用户在 Supabase 跑 watchlist_migration.sql

- [done] 2026-06-19 · review-followups · 5 改进: calibration→Supabase / 决策数字护栏 / ETF 价格确定性计算 / HOLD 影子评判 / 派生信号标注 · files: backend/dashboard/calibration.py, backend/dashboard/decision.py, backend/dashboard/journal.py, supabase_schema.sql, frontend/app/page.tsx, frontend/app/_lib/data.ts · 待用户在 Supabase 跑 calibration_migration.sql

- [done] 2026-06-18 · setup · created CLAUDE.md + this coordination worklog · files: CLAUDE.md, COORDINATION.md
