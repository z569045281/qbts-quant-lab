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
