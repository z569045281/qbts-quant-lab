# 🏁 千元挑战 bot(第二期)

> 读这份文件的时机:改 `challenge2.py`、/challenge 页、Alpaca 下单逻辑。

`backend/dashboard/challenge2.py`,跑在 QuoteFunction 的 `minute%15==2` 行情时段跳
(偏移躲开 `%5` 的 SMC 分钟)。$5000 纸面 sleeve 走 **Alpaca paper**(真下单,REST 用
`requests` —— **alpaca-py 故意没进 Lambda 镜像**)。

## 规则

- 进场 = `challenge_basket` 全场之选(87% market + GTC bracket TP +11.5% / STOP −12%)。
- +10% 触碰 = liquidate(**触碰即落袋**;bracket 只是后备)。
- **🏁 马拉松模式(2026-07-10 用户改规则)**:不再 +10% 判赢收手 —— $5500 只是里程碑
  (首次报喜一次),持续交易;落袋当日冷却、次日再进场(否则下一跳原价买回
  白付点差);每跳记 `equity_curve`(15min 粒度,cap 2000 点)
  → /challenge 页 SVG 资金曲线。
- **终点 2027-08-15**(2026-08-18 续跑)。原终点 8/15 到点,08-17 自动 `⏱ CHALLENGE ENDED`
  收在 **$5,051.66(+1.0%,峰值 $5,388.92)**;用户「我没说停不许停」→ 状态改回 `running`、
  终点延一年,权益/曲线/峰值全部承接不重置。
- **⚠️ 目前没有任何硬性停手线**:floor 已于 2026-07-21 用户拍板取消(`floor_line=null`),
  当时的理由是「跑到 8/15 到期为止」—— 终点延长后,这个 sleeve 事实上只剩 −12% 单笔止损
  兜底,没有整体死线。要重设地板得用户开口。
- 自门控在 09:30–16:00(夜盘不会误交易)。

## 状态与前端

State = Supabase `crypto_challenge` id='current'(round 1 归档在 'round1-2026-07');
前端 /challenge 动态渲染。

## ⚠️ Round-1 教训(必须记住的执行细节)

**bracket 子单还挂着股票时,普通 market sell 会被 REJECT** —— 出场一律走
`DELETE /v2/positions/{sym}?cancel_orders=true`。(round 1 的 "LIQUIDATE" 根本没成交;
遗留仓位 2026-07-08 才清掉。)

## 战果与冷水(round 1,2026-07-09 收官)

$1000 → $1106.97(+10.7%),5 个交易日,2/2 全胜。**这是 n=1**:回测首达赢面 ~60%,
意思是同一打法**四成的月份会输**;每注 EV ≈ +1.2% 费前;赢的主力是"七月大盘顺风 × 3× 杠杆贝塔",
不是选股 alpha。**别放大真钱、别连续滚动去撞那 40%。**

可迁移的六条纪律(打法骨架,完整版见 [../mining.md](../mining.md)「千元挑战收官·打法提炼」):
先写目标函数再设计策略(优化**首达概率**不是期望收益)· 载具用 3× 指数 ETF 不用单票(要波动
不要故事,躲财报/增发/FDA 雷)· 趋势门(>50 日线且周动量为正,红灯不进场)· **出场在进场
那一刻就写死**(券商原生括号单)· 赢线和死线先于第一笔交易定义 · 注码输光不影响生活,
利润落袋不滚入下一把。

Secrets:`ALPACA_API_KEY` / `ALPACA_SECRET_KEY`(空 = bot 关),见 [SECRETS.md](SECRETS.md)。

## 🎯 QBTS $1000 · Claude 自营(2026-09-18 起)

用户点单:「给你 1000 刀自由买卖 QBTS,自己想办法赚钱,至少每月赚回订阅费,记录买卖」。
**纸面盘**(Alpaca paper,与 challenge2 同账户;本 bot 只碰 QBTS,challenge2 只碰杠杆 ETF)。

- 代码:`backend/dashboard/qbts_challenge.py`;Lambda 15:52–15:57 ET 窗口每天一次(`last_run` 去重)
- 状态:`crypto_challenge` 表 id=`qbts1000`(零迁移);前端 `/challenge` 页顶部卡片
- 规则:在册「QQQ50×波动率目标」原样执行(replay.py `volreg` 同一公式),收盘前 8 分钟按实时价
  调仓,变动 <10% 权益不动,无止损。**不新造信号**。
- 目标:用户同日改口「尽可能赚钱,别管订阅费」→ 月报对照 = 同月一直拿着 QBTS。
- 上线时写下的预期(不许事后改):近 12 月月均 −0.1%、6/12 个月亏、3/12 个月 ≥+10%;
  定型后(07-09 起)−31% vs 同期拿着 QBTS −23%。**没有证据支持每月稳定赚钱。**
