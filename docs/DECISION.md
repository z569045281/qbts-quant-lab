# 决策大脑 decision.py

> 读这份文件的时机:改提示词、改模型、动交易计划的数字护栏、动影子决策。

## 主决策

`backend/dashboard/decision.py` — THE brain:一次 **Fable 5**(`claude-fable-5`)调用 →
trade-plan JSON,**auto-fallback to Opus 4.8** on any primary failure(`decision.model`
记录到底是谁答的 —— Fable 曾被停用过一次,publish 必须活下来)。同一次调用还返回
`system_notes`(AI 每日自检:数据问题/改进建议 → 仪表盘「AI 系统自检」卡)。

**模型分工**:Fable 5(决策,回退 Opus 4.8)· Sonnet 4.6(因子生成)· Haiku 4.5(新闻/反思/
地缘/自检)· DeepSeek V4 Pro(影子 + SpaceX 专机)。

**提示词结构(2026-07-06 v2.0 重写)**:旧"通用基金经理"人设已废弃。现版把回测验证结果
直接灌进 system prompt —— **A 收益DNA / B 一级信号清单(含即时读数)/ C 已判死推理路径 /
D 执行军规**,让模型按证据分层加权。改 B 级清单的阈值时,记得同步
`waiting_for.py`(「今天在等什么」卡与它一一对应)。

**必填 `bold_call_5d`**(up/down 强制二选一,与 action 解耦)—— 观望日也要留下可评分的方向
表态,否则整月 HOLD = 零样本。

## 数字护栏(`_sanitize_decision`)

提示词里的散文规则不是自执行的,数值规则必须落在代码里:

- **止损下限按 regime 强制加宽**:模型返回 entry/stop/target 后,计算
  `1.5×ATR14`(`regime=="expansion"`)或 `1.0×ATR14`(其它),模型给的止损比这更紧就在代码里
  拉宽。出处见 [LESSONS.md](LESSONS.md) 2026-07-22 那条(06-25 SHORT_QBTZ 被 1.03×ATR
  的止损洗出去,1.5×ATR 本可扛过去并吃到目标)。
- 夹信心区间、补 RR、剔除离谱价位。
- 失效价换算锚用 QBTX/QBTZ **隐含公允价**,不用陈旧的最后成交价。

## 影子决策(全部零决策权:不推送、不驱动交易、不进 edge)

**① DeepSeek V4 Pro 影子**(`generate_shadow_decision`, 2026-07-13,需 `DEEPSEEK_API_KEY`)
—— 同一份 prompt 每天跑一遍(`deepseek-v4-pro`, api.deepseek.com, ~$0.02/天),挂在主决策
`shadow_ds` 字段随缓存/payload 走。决策卡可 Fable/DeepSeek 切换(v2.14.0);journal 记
`ds_bold_call`,与 Fable `bold_call_5d` **同一套 fwd5 口径**评分(`audit.py` ② 🥊 表态vs5日)
→ **8/15 影子考场宣判,赢了才谈换岗**。Blank key = 影子全关,主决策零影响。
方向单 <5 bar 提前触发评分的日子 fwd5 无数据,该日两模型表态不计分(方向单稀有,可忽略)。

**性能**(2026-07-24):影子与主决策在 `get_or_generate_decision` 里用 `ThreadPoolExecutor`
**并发**跑,墙钟从 sum 降到 max —— DeepSeek 是推理模型,全量 prompt 30-60s,串行会让用户干等。

**② v1 反向影子**(`edge.py::compute_edge_v1` + `decision.py::_invert_v1_shadow`, 2026-07-21)
—— 原始 v1 元模型(2026-07-17 前上线版,22 条已判 **21% 命中,Wilson95% 上界 38%<50%,
显著劣于随机**)从 `edge.py` 里**逐字节复现**(`_build_contributions` 抽成 v1/v2 共用;
v1 走原始无上限裸加 + 无 regime 项 + EV±1% 阈值,`compute_edge`(v2)行为完全不变)。
表态**整体反向**当影子:纯机械($0,不调任何模型),`snapshot['edge_v1_shadow']` →
`decision['shadow_v1_inverse']` → journal `v1inv_bold_call` 同一套 fwd5 评分 →
`audit.py` ② 🥊 三行同框(Fable/DeepSeek/v1反向)。**假设未证实**:21% 可能是稳定的反向
alpha,也可能只是 n=21~24 的小样本噪声——8/15 一起宣判,不预设结论。

## 与其它模块的关系

- **SMC playbook 是「整体评判标准」**(覆盖零散信号),渲染在决策卡顶部,见 [SMC-PLAYBOOK.md](SMC-PLAYBOOK.md)。
- 各信号如何进 prompt、权重多少,见 [SIGNALS.md](SIGNALS.md) 与 [AUDIT-AND-EDGE.md](AUDIT-AND-EDGE.md)。
- **宏观段纪律**:对"已发布但 actual 未回填"的事件必须显式标注 + 禁令(2026-07-14 把 CPI
  **前值 0.5%** 当当日公布值喊"爆表"、实际 −0.4% 方向全反,已修)。
- **多票聚合数字一律以本票口径为准**(内部人卖出 $988M 三票合计 vs QBTS 自身 $35.4M)。
