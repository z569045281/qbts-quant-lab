# CLAUDE.md — QBTS Quant Lab

Instructions for any Claude session working in this repo. Auto-loaded every session.
**这个文件只放"路标 + 永远适用的铁律";细节全在 `docs/` 里,按下面的表按需读。**

---

## 🗺️ 动手之前 — 任务文档地图

**开始任何任务前,先对照此表,读掉对应的文件。** 一行都不读就动手 = 大概率重犯已经修过的 bug。

| 如果任务涉及… | 必须先读 |
|---|---|
| **任何任务(第一步)** | [COORDINATION.md](COORDINATION.md) — 看别的会话在改什么,并登记自己 |
| 第一次进这个仓库 / 数据怎么流 / 本地怎么跑 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 提交 / push / 发版 / 前端可见改动 | [docs/DEPLOY.md](docs/DEPLOY.md) |
| 新增或改动 API key、"云端没生效" | [docs/SECRETS.md](docs/SECRETS.md) |
| `aws/**`、Lambda、定时调度、盘中分钟槽位 | [docs/AWS-LAMBDA.md](docs/AWS-LAMBDA.md) |
| 行情抓取、yfinance、`as_of`、夜盘、时区 | [docs/MARKET-DATA.md](docs/MARKET-DATA.md) |
| Supabase 表、迁移、写库、"页面空白" | [docs/SUPABASE.md](docs/SUPABASE.md) |
| 决策提示词、`decision.py`、模型选择、影子决策 | [docs/DECISION.md](docs/DECISION.md) |
| SMC、playbook、15m 扳机、TRIGGER 推送 | [docs/SMC-PLAYBOOK.md](docs/SMC-PLAYBOOK.md) |
| 任何信号模块(NW/地缘/SEC/情绪/游击战/等什么卡/宏观) | [docs/SIGNALS.md](docs/SIGNALS.md) |
| edge 权重、校准、台账评分、8/15 审判、`audit.py` | [docs/AUDIT-AND-EDGE.md](docs/AUDIT-AND-EDGE.md) |
| 「系统到底有没有用」/ 月度复盘 / 为什么天天观望 | [docs/REVIEW-2026-07.md](docs/REVIEW-2026-07.md) — 首次全面体检 |
| `/watch` 扫描、`/dca` 定投、`/factors` 战绩、产品判断 | [docs/SURFACES.md](docs/SURFACES.md) |
| 千元挑战 bot / `/challenge` | [docs/CHALLENGE.md](docs/CHALLENGE.md) |
| SpaceX `/spacex` | [docs/SPACEX.md](docs/SPACEX.md) |
| **改任何前端代码** | [frontend/AGENTS.md](frontend/AGENTS.md) — Next 16 有破坏性改动 |
| 回测、新策略、"能不能搞个指标" | [mining.md](mining.md) — **先查已判死清单** |
| 改标签/开关/窗口/提示词规则前 · 任何市场事实问题 | [docs/LESSONS.md](docs/LESSONS.md) |

---

## ⚠️ 多会话协作(READ FIRST)

Several Claude sessions may run at once. Sessions are isolated — they do **not** see each
other's context. Coordinate through files + git:

1. **动工前读 [COORDINATION.md](COORDINATION.md)**,看别人在做什么、认领了哪些文件。
2. **追加一条自己的记录**:时间戳、一行任务描述、要碰的文件/区域;完成后标 `[done]`。
3. **绝不编辑别的活跃会话已认领的文件。** 需要就换一块切片,或在 COORDINATION.md 写交接。
4. **两个会话绝不同时编辑同一个工作目录** —— 磁盘是最后写入者赢,git 状态会打架。
   真要并行,各给一个 worktree + 分支:`git worktree add ../qbts-<task> -b <task>`,
   然后靠 commit / `git log` / PR 协作,不靠共享工作树。
5. **小步频繁 commit**,让其它会话/worktree 看得见。**Push 到 `main` 只在用户开口时** ——
   `main` 会触发部署。

---

## 🔒 永远适用的铁律

- **我有 ADHD,请直接说重点、不要废话,先给出可执行步骤。**
- **决策/交易相关的四条铁律不可动**(用户 2026-07-09 授权全自主改仪表盘时明确划的红线):
  投机仓 ≤ 总资产 10% 总闸 · 验证期不加真金 · 判死的策略不复活 · 真金只给建议不代下单。
- **测量期**:scan 纸面账本 / 决策台账 / 校准都是刚开始记 —— **所有信号统计上 UNPROVEN**。
  别在记录显出 edge 之前劝用户加仓;下一轮优化由累积结果驱动。见
  [docs/AUDIT-AND-EDGE.md](docs/AUDIT-AND-EDGE.md)。
- **任何股票/市场事实先查再答**(WebSearch + repo `yfinance`),永不凭训练记忆;别报精确顶底。
- **前端可见改动必须同步升 `frontend/public/version.json`**(细则见 [docs/DEPLOY.md](docs/DEPLOY.md))。
- Commit 结尾带 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **判死的策略家族没有新证据不得重提**([mining.md](mining.md) 已判死表 + 记忆
  `qbts-range-trading-no-edge` 同一待遇)。

## 这是什么(一句话)

Personal one-screen trading dashboard for **QBTS** (D-Wave Quantum), traded via leveraged
ETFs **QBTX** (2× long) / **QBTZ** (2× short). Daily it answers: buy QBTX / buy QBTZ / hold,
with an executable trade plan (entry/stop/target/RR/size), key drivers, and catalysts.
架构、模块地图、本地运行:[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 这个文件 vs 记忆库

`CLAUDE.md` + `docs/` = 约定与操作手册(跟着代码走)。跨会话的**持久事实**(用户是谁、
授权范围、已定型的判断)在项目记忆 `memory/MEMORY.md`,每个会话启动时自动加载。
学到新教训 → 写进 [docs/LESSONS.md](docs/LESSONS.md);新的持久事实 → 写进记忆库。
