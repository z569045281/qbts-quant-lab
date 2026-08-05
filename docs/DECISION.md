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

## 🔔 watch_levels —— 决策卡自己的触发线推送(2026-08-04)

**出身**:08-03 的卡写着「收盘放量站上 $18.88 → 小仓买 QBTX」。当晚三个条件全中
(收 $19.98 / 量 2444 万 / QQQ +1.76%),**但没有任何东西通知用户** —— 美股收盘 =
墨尔本早上 6 点。他第二天醒来看到已经涨了 10% 才追。

系统里特调 / SMC playbook / 事件日 / 催化剂 / 地缘 / 周末BTC / 挑战 bot / 游击战全都有
ntfy,**唯独决策卡每天给的那条线没有** —— 因为它只活在 `entry_condition` 的自由文本里。

**改动**:决策输出新增结构化 `watch_levels: [{price, side: above|below, action_cn}]`,
由 `decision_trigger.maybe_trigger_push` 在**收盘窗口(16:02–16:30 ET)**判一次,越线即推。

三条纪律:
- **只推事实,不新造判断**。价位与动作原样来自当天已发布的卡。它是闹钟,不是信号源。
- **只认收盘** —— 盘中穿越不算(盘中预挂已判死,推送口径必须与决策口径一致)。
- **做空条目推不出去**:`_clean_watch_levels` 在源头丢弃 + 推送层二次拦截。
  做空 QBTS 全部路径第 7/9/13/23 轮四次判死 —— **铁律不靠单点防守,更不靠模型自觉**。

同批加的 **⛔ 做空常驻禁令**(以前只有事件日那段有):`action` 不得 SHORT_QBTZ、
`etf_ticker` 不得 QBTZ、正文不得出现"做空/战术空/买 QBTZ"。起因是 08-02 的卡写了
「跌破 $17.84 可用 QBTZ 做 1-3 天战术空」——**技术位被跌破不是新证据**。
唯一例外:用户已持有 QBTZ 时可以给离场建议。

⚠️ `dec_trigger` 状态存在 live_quote(整块覆写),非工作跳必须 `return prev`,
否则重复响铃 —— 见 [LESSONS.md](LESSONS.md) 2026-07-31 那条。

## 📊 财报预期基准 `earnings.py`(2026-08-05)

**出身**:决策 AI 自己在 `system_notes` 里报的缺口 ——「财报仅 2 天后,系统应增加一段
财报预期数据,当前只有日期没有预期基准,**无法评估 surprise 空间**」。用户点单落地。

它说得对。以前 prompt 只有一行「下次财报: 2026-08-06(2 天后)」,模型只能回一句
"财报临近、波动放大、谨慎" —— 放之四海皆准的废话。**没有基准就没有 surprise**。

三块数据(全免费,yfinance):
1. **一致预期** —— EPS/营收的均值与高低区间。区间本身是信息:分歧越大越说明没人知道。
2. **历史财报当日实测** —— |涨跌| 与高低振幅的中位/均值/最大 + 方向胜率 + 近 8 次明细。
   ⚠️ **中位是主口径**:2025-05-08 那次 +51.2% 会把均值拉到没法用。
3. **历史 surprise** —— 近 4 次实际 EPS vs 预期(QBTS 是 +46/−46/+25/−47,两边都打脸)。

**首日实测(2026-08-05,财报前一天)**:n=16 · |涨跌| 中位 6.2%/均值 11.3%/最大 51.2% ·
当日高低振幅中位 15.8% · 方向中位 −2.3%、上涨率仅 38%。杠杆 ETF 口径 ×2。

三条纪律写死在段尾:
- **这段不产生方向** —— 第三十二轮已实测「财报前买入」判死,不得当入场理由。
- 正确用途是**定仓位与定时点**(该减多少、什么时候减),不是判断涨跌。
- 财报是二元事件,**系统对它没有任何预测能力**,不许在 summary 里假装有。

样本 <5 次 → 只说"样本太少"不给统计;拉取失败 → 显式说缺(段落静默消失会让模型自己猜,
AI 自检 07-20 的旧教训)。**刻意不传本仓的 df_d**:缓存日线只有 2 年、只够 8 次财报,
模块自己拉 max 历史才够 16 次。
