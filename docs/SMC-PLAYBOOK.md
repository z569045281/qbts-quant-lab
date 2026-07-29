# SMC 顺势纪律 Playbook

> 读这份时机:动 `smc.py` / `intraday_smc.py` / 15m 扳机 / TRIGGER 推送 / 决策卡顶部区块。

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
15m 同向 **CHoCH** **且** 收盘确认的 **VMC dot**。

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

输出带 5 项 ✓/✗ 清单 + entry/stop/TP1/TP2/RR;UI 渲染为卡片顶部区块,`decision.py` 把它框成
**整体评判标准**(覆盖零散信号)。

**VMC 绿/红点是复刻**:`backend/dashboard/wavetrend.py`(LazyBear WaveTrend —— VMC/Cipher-B
本质就是 WT 穿出超卖/超买)。VMC 本身是闭源 TradingView 脚本,把它当**忠实近似**,不是像素级一致。

## 盘中刷新 + TRIGGER 推送

`backend/dashboard/intraday_smc.py`,接在 `aws/lambda_handlers.py::quote_handler`。

每日 09:00 的 publish 只算**一次** playbook —— 但它的 TRIGGER(15m CHoCH + VMC dot)是盘中
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

## 结构引擎 = LuxAlgo 忠实移植(2026-07-29,`epoch = luxport-20260729`)

用户贴来 LuxAlgo「Smart Money Concepts」Pine 源码后照它重写了 `lux_structure()`。
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
