# 🏁 千元挑战 bot(第二期)

> 读这份文件的时机:改 `challenge2.py`、/challenge 页、Alpaca 下单逻辑。

`backend/dashboard/challenge2.py`,跑在 QuoteFunction 的 `minute%15==2` 行情时段跳
(偏移躲开 `%5` 的 SMC 分钟)。$5000 纸面 sleeve 走 **Alpaca paper**(真下单,REST 用
`requests` —— **alpaca-py 故意没进 Lambda 镜像**)。

## 规则

- 进场 = `challenge_basket` 全场之选(87% market + GTC bracket TP +11.5% / STOP −12%)。
- +10% 触碰 = liquidate(**触碰即落袋**;bracket 只是后备)。
- **🏁 马拉松模式(2026-07-10 用户改规则)**:不再 +10% 判赢收手 —— $5500 只是里程碑
  (首次报喜一次),持续交易到 **2026-08-15**;落袋当日冷却、次日再进场(否则下一跳原价买回
  白付点差);floor **$4250 硬性停手**不变;每跳记 `equity_curve`(15min 粒度,cap 2000 点)
  → /challenge 页 SVG 资金曲线。
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
