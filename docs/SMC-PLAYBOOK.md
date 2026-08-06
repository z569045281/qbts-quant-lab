# SMC 顺势纪律 Playbook

> 读这份时机:动 `smc.py` / `intraday_smc.py` / 15m 扳机 / TRIGGER 推送 / 决策卡顶部区块。

> ## ⚠️ 2026-08-06:整套 LuxAlgo 已按用户点单撤回
>
> `lux_smc.py`、`smc['lux']` 原版面板、`SMC.docx`、swing(50)/背离那几个派生字段
> **全部删除**;结构引擎回到本模块自己的 `analyze_structure`,`k=2` 保持,⑤VMC
> 保持删除状态。`SMC_EPOCH = legacy-k2-20260806`。
>
> **撤回理由是灵敏度,不是"LuxAlgo 有 bug"**。用户原话:「之前的 smc,在 16 块涨到
> 17 块的时候就说已经从空转多了,很灵敏,我想要那个版本」。逐日回放坐实:07-24
> $16.21 → 07-27 $19.51 那波,**只有 `analyze_structure`(k=2)翻多**,k=8 与
> LuxAlgo 从 6 月底一路 bearish 到 08-05 一次没翻。
>
> 两套引擎的差别是一句话:**本引擎认所有未被破的历史摆动高点(破任一个即翻多),
> LuxAlgo 只认「当前那一个」pivot(常年远在天上,所以几乎不开口)。**07-29 那次
> 换引擎把这个性质定性成缺陷(git `ef53ffa`),那是单方面的 —— 它同时是用户唯一
> 想要的功能。要更钝就调大 `_DAILY_SWING_K`,**别再换引擎**。
>
> ⚠️ 灵敏是单向的:**翻多快、翻回空慢**(翻空需收盘跌破未被破的摆动低点,而反弹
> 会抬高近期低点)。07-29 价格跌回 $16.18、低于触发翻多的位置,锁仍是 bullish。
> 下面第 141 节起关于 LuxAlgo 引擎的描述均为**历史存档**,代码已不存在。

`backend/dashboard/smc.py::build_playbook`,挂在 `smc['playbook']`;**只用于 QBTS 决策页**,
自选扫描仍用旧的 `analyze_smc` 字段(未动)。这是一台建立在基础 SMC 读数之上的三模块状态机。

## 三模块

**① 全局方向锁** = 只读**最新**日线结构标签(`last_event.dir`,BOS **或** CHoCH)→
`lock` bull/bear/none;bull = 只做多(回踩),bear = 只做空(诱多)。
> 事件级背书见 [../mining.md](../mining.md) 第十九轮:BOS↓ 后 5d −2.22% vs 基线 +2.69%
> (tΔ=−2.33)。但月球年提醒:锁不是万能,疯牛能凿穿一切结构。
> 第二十三轮进一步:**bear lock 是"别做多"的过滤器,不是"该做空"的扳机**。

**② 降维中继状态机**:`WAIT → ARMED → TRIGGER`。
ARMED = 价格进入 discount(bull)/premium(bear) 越过 fib-0.5 均衡点 **且** 触碰次级
时间框(1h 重采样出的 4h,或 1h)的中继订单块。TRIGGER(AND 逻辑)= ARMED **且** 新鲜的
15m 同向 **CHoCH**。

**③ FVG**:entry = FVG∩OB 重叠(共振狙击点);TP1 = 前方最近未回补 FVG 的近端(止盈磁吸);
TP2 = 区间极值。

## 2026-07-01 精修(每条都是修过的 bug)

- premium/discount 锚定到**打出最新结构标签的那一段 swing 的 dealing range**
  (`_dealing_range`:向下破位 → top = 破位前那个 LH,bottom = 之后的最低低点),
  **不是全局 hi/lo**(那会把 0.5 线抬虚)。
- entry 强制 **≤ $1.00 宽** —— 钻到中继区内最紧的 1h/4h FVG∩OB 汇合处(实在不行裁到近端边),
  免得一个宽日线 OB 把 RR 拖垮。止损贴**精修后的 entry**,不贴 HTF 区。
- **风险熔断 `rr_veto`**:RR < 2.0 → entry 无效 → 状态强制「观望」(`risk_note` 卡上显示琥珀色)。
- TP1 从 **entry 边之外**起算,免得覆盖 entry 的 FVG 冒充目标触发假 veto。

输出带 4 项 ✓/✗ 清单 + entry/stop/TP1/TP2/RR;UI 渲染为卡片顶部区块,`decision.py` 把它框成
**整体评判标准**(覆盖零散信号)。

## 2026-08-04 用户点单:k 回 2 + 纪律只留 ①②③④

- `_DAILY_SWING_K` **8 → 2**。07-29 那次 2→8 是给**旧结构引擎**打的止血带,病根已被
  LuxAlgo 移植根治(mining.md 第三十三轮复核:k **不进方向锁**,只喂 sweeps /
  dealing range / 中继 OB)。k=2 摆动点更密 → 这三处的粒度更细、离现价更近。
- 清单**删掉原 ⑤「15m VMC 点(收盘确认)」**,只留 ①方向锁 ②折价/溢价 ③次级别中继 OB
  ④15m 同向 CHoCH。**状态机同步松了 AND** —— TRIGGER 不再要求 VMC 点,否则会出现
  「4/4 全绿却还是预警」。`dot_ok`/`dot_bars` 仍照算并随 `ltf15` 带出(留给 8/15 审判
  回答"它到底加过分没有"),但**零否决权**。
- ⚠️ 少一道 AND ⇒ **TRIGGER 会变多 ⇒ ntfy 推送会变多**,预期内。
- 两处都改口径 ⇒ `SMC_EPOCH` 另分一代 **`k2-nodot-20260804`**,审判别和
  `luxport-20260729` 的记录混一个池子。

**VMC 绿/红点的复刻仍在**:`backend/dashboard/wavetrend.py`(LazyBear WaveTrend ——
VMC/Cipher-B 本质就是 WT 穿出超卖/超买),游击战模块 (`guerrilla.py`) 还在用它。
VMC 本身是闭源 TradingView 脚本,把它当**忠实近似**,不是像素级一致。

## 盘中刷新 + TRIGGER 推送

`backend/dashboard/intraday_smc.py`,接在 `aws/lambda_handlers.py::quote_handler`。

每日 09:00 的 publish 只算**一次** playbook —— 但它的 TRIGGER(新鲜的 15m 同向 CHoCH)是盘中
转瞬即逝的,一天一算永远抓不到。修法:**每分钟的 QuoteFunction** 在 `minute % 5 == 0`
(pre/regular/post)重算**便宜版** playbook(缓存的日线/1h + **新鲜 15m**;无 LLM → ~$0),
写进 `live_quote.data['smc']`,并在非重算分钟**结转**上一次结果以免闪烁。前端
(`page.tsx`)**优先用 live playbook**(`live?.smc?.playbook ?? snap.smc?.playbook`)+
显示「盘中实时」脉冲。

**推送**:只在**上升沿**进入 TRIGGER 时发一条 `ntfy.sh`(去重靠从 `live_quote` 读回的上一状态)。
`NTFY_TOPIC` 空 = 不推送(playbook 照常刷新+显示)。标题保持 ASCII(HTTP header 是 latin-1),
中文细节走 UTF-8 body。相关陷阱(sys.path / `smc_err`)见 [AWS-LAMBDA.md](AWS-LAMBDA.md)。

## 定位

**它是风控/纪律工具,不是收益引擎**(mining.md 已判死:全保真 40 天仅 1 枪;ARMED 版 +5.5%/年)。
和其它信号一样 **UNPROVEN**,直到纸面台账/journal 的记录真的显出 edge —— 见 [AUDIT-AND-EDGE.md](AUDIT-AND-EDGE.md)。

## 整张指标的忠实移植 = `backend/dashboard/lux_smc.py`(2026-07-29 第二步)

用户把 LuxAlgo「Smart Money Concepts」Pine v5 源码放进仓库根目录 `SMC.docx`
(CC BY-NC-SA 4.0 © LuxAlgo),要求**复刻到仪表盘**。当天分两步:上午只移植了结构
那一段(见下一节),下午把**整张指标**单遍逐 bar 搬进 `lux_smc.py::run_lux`:

| 组件 | 对应 Pine | 说明 |
|---|---|---|
| internal(5) / swing(50) 结构 | `getCurrentStructure` + `displayStructure` | 两级**同一遍**跑,因为 internal 事件的成立条件之一是 `internalHigh ≠ swingHigh` |
| Strong/Weak High-Low | `updateTrailingExtremes` / `drawHighLowSwings` | 标签由 **swing** trend 决定 |
| 溢价 / 均衡 / 折价 | `drawPremiumDiscountZones` | 5% 带 + 47.5–52.5% 均衡带,锚 trailing extremes |
| 订单块 | `storeOrdeBlock` / `deleteOrderBlocks` | pivot→破位区间里 `parsedHigh/Low` 的极值那一根;高波动 bar(振幅 ≥ 2×ATR200)高低**对调** |
| FVG | `drawFairValueGaps` / `deleteFairValueGaps` | 自适应阈值 = 累计平均实体% × 2 |
| EQH / EQL | `getCurrentStructure(3, true)` | 阈值 0.1 × ATR200 |
| MTF 高低线 | `drawLevels` | PDH/PDL(日线图=当根)· PWH/PWL · PMH/PML |

**接线**:`analyze_smc` 每次调用 `run_lux` 跑一遍全量日线 → 结构两级直接用它;
面板经 `_build_lux_panel` 挂在 `smc['lux']`,前端决策页 4.7 区新增「📐 LuxAlgo 原版面板」
(整行宽,盘中 live 快照同样带)。0.05s / 500 根,零外部依赖。

### ⚠️ 它**零决策权**,和 playbook 是两套口径

面板**不进** `score`、不进 edge、不驱动状态机、不进决策 prompt。原因是原版和我们
playbook 的定义本来就不同,硬合成一套会毁掉已经在测量期里的信号:

| | LuxAlgo 原版 | playbook(我们的) |
|---|---|---|
| 溢价/折价区间 | trailing extremes:$12.75–46.75 → 现价 **14%** | dealing range:$12.75–31.55 → 现价 **26%** |
| 订单块 | pivot→破位区间的极值那根(07-28 供给 $23.25–24.73) | 破位前最后一根反向蜡烛(供给 $22.44–23.62) |
| FVG 回补 | **不对称**(见下) | 对称,且只看最近 90 根 |

原版的 trailing extremes 会把均衡线抬到 **$29.75**(2025-10 那个 $46.75 高点还在
拉着),对 QBTS 这种一年 40× 又腰斩的票不是可用的交易读数 —— 这正是 07-01 精修
当初改用 dealing range 的理由。所以两者并存、**卡上各自标注来源**,不互相覆盖。

### ⚠️ 照抄了原版 FVG 回补规则的不对称

源码 `fairValueGap.new(currentHigh, last2Low, BEARISH, …)` 把看跌缺口**数值更低**
的那条边存进了 `top` 字段,而删除条件是 `high > top` ——

- 看涨 FVG:价格**完全打穿**才消除
- 看跌 FVG:**碰到近端就消除**

后果:未回补列表里几乎只剩看涨的陈年缺口(QBTS 全量日线上 7 个,全是 $0.91–$9.83
那种一路上来没填过的),越老离现价越远。**卡上写明了,别当成近处支撑**。这是原
指标的行为,用户图上看到的就是它 —— 要改得先决定"我们到底还要不要和图一致",
别偷偷修成对称的。

### 面板会标注哪些是原版默认关的

用户图上默认只开:internal/swing 结构、内部订单块、EQH/EQL、Strong-Weak High/Low。
**FVG、swing 订单块、溢价折价区、MTF 线原版默认是关的**,他不一定见过 —— 所以卡上
每一块都标了「原版默认开/关」。

### 验证(33 条断言全绿)

逐条钉住 Pine 规则:`ta.rma/ta.atr` 递推恒等式 · `ta.crossover` 比的是上一根的 level ·
同一 pivot 只点燃一次(构造收盘两次上穿 $11.00 但只出一个事件)· `trend=0` 时首个
破位是 BOS · `internalHigh == swingHigh` 时 internal 事件被抑制 · 看涨 FVG 需打穿 /
看跌 FVG 碰近端即删 · 自适应阈值挡掉无实体推动 bar · **真实日线全量**上每个订单块
都确实落在 pivot→破位区间的极值那根且从未被回补 · 58 根高波动 bar 的高低确实对调 ·
溢价折价带系数 · PWH/PWL/PDH/PDL · 空输入不炸。

**信号路径零变化**:换引擎前后 `analyze_smc` 的完整输出逐字段对比,**只有 `level`
字段的小数位**(20.93000030517578 → 20.93)不同,signal/label/lock/state/entry/stop/
TP/RR/checklist 全部一致 → `SMC_EPOCH` 不分代。

## 结构引擎 = LuxAlgo 忠实移植(2026-07-29,`epoch = luxport-20260729`)

用户贴来 LuxAlgo「Smart Money Concepts」Pine 源码后照它重写了 `lux_structure()`。
(同日下午 `lux_structure` 已改为 `lux_smc.run_lux` 的薄封装 —— 见上一节。)
**旧的 `analyze_structure` 与原算法三处都不一样**,已整体删除:

| | 旧实现 | LuxAlgo |
|---|---|---|
| pivot 检测 | 对称 fractal(前后各 k 根) | `leg()` **单边前视**:`high[size] > ta.highest(size)`,pivot 在 leg 翻转时落定 |
| 破坏判定 | 遍历**所有**历史摆动高点,破任一个就翻多 | **只认「当前那一个」** pivot,破了打 `crossed` 永不复用 |
| crossover | 只要 `close > level` | 还要求 `close[1] <= level` |

**这才是「多头锁定」的真凶**:下跌途中旧实现会攒下一队没被破的老高点,07-27 一根
+20.4% 破掉了三天前的 $18.02 就翻多 —— 而 LuxAlgo 眼里当前 internal pivot high 是
**$24.73**,19.51 根本够不着,所以它不翻。改 k(2→8)只是压住症状,换引擎才是根治。

### 两级结构必须同时暴露

LuxAlgo 本来就同时跑两套,而且**方向常年不一致**:

```
internal(5)  bearish   ← 方向锁用它;K 线着色也是它
swing(50)    bullish   ← 图上「Strong/Weak Low」标签由它决定
```

用户就是因为只看到其中一个才以为是 bug。现在 `swing_trend` / `trend_divergence` /
`strong_low_label` 全部随快照带出,决策 prompt 与卡片都明示背离,并要求背离时
按「逆大势的战术单」处理(仓位更小、持有期更短)。

**外部验证**:移植代码预测「图上底部标签 = Strong Low」,与用户截图一致。

## 附:日线摆动敏感度 k(同日 2 → 8;现仅用于 sweeps/dealing range/order block)

用户对着 TradingView 的 LuxAlgo(swing 50)问「为什么 SMC 显示多头锁定,这是重大 bug」——
查下来不是显示错,是**参数定错了尺度**。07-27 那根 +20.4% 击穿 $18.02(3 天前的一个
小高点)→ 看涨 CHoCH → 日线锁翻多,而同期价格在所有均线下方、7 月累计 −29%。

| k | 当前趋势 | 近1年翻转 | 平均维持 |
|---|---|---|---|
| 2(旧) | **bullish** | 6 次 | 35.5 天 |
| 3 | bullish | 6 次 | 35.5 天 |
| 5 | bearish | 5 次 | 42.6 天 |
| **8(新)** | **bearish** | 5 次 | 42.6 天 |
| 20(≈用户图) | bearish | 1 次 | 213 天 |

**k=2 是唯一给出 bullish 的设置** —— 前后各 2 根就算一个摆动高点,在 ATR 9.6% 的票上
那是内部噪声,不是结构。拿它下「不做空」这种指令性结论,与 07-28/07-29 那两条教训同宗:
**读数在它没有分辨力的尺度上假装自己有分辨力。**

LTF(1h/15m)的 k 不动 —— 日内本来就该用短摆动,而且它们不驱动方向锁。

⚠️ **审判须分代**:`smc.epoch = "k8-20260729"` 随快照带出,8/15 按它分组统计,
别把两代混在一起算胜率。

## ⛔ 空头扳机不响铃(2026-07-29)

改 k 之后空头 playbook 的 RR 从 1.79 变成 **5.84** —— 以前它是被 `RR<2 熔断`**顺手**
挡住的,现在能过闸了。**靠另一道闸的副作用来维持铁律,等于没有维持。**

`maybe_notify_trigger` 现在显式拦下 `lock == "bear"`:做空 QBTS 的全部已知路径均已判死
(第十三轮空头家族终审 / 第二十三轮 bear lock / 第二十八轮又新判死两条),档案写明
QBTZ 唯一残留用途 = 未来若出现新的、独立验证的看空信号,而它目前不存在。

bear lock **仍然照常**进卡片和决策 prompt 当方向过滤器与风控背景 —— 只是不推
"去做空"这个动作。
