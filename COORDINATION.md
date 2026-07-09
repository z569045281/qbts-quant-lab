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

- [done] 2026-07-09 · [fable] mining-round20 · 第二十轮:SEC FTD 交割失败(半月档,出版滞后诚实建模,信息含量诊断版+可交易版分开),预注册判活 · files: mining.md

- [done] 2026-07-09 · [fable] mining-round19 · 第十九轮:裸 BOS/CHoCH 结构事件研究(smc.py 同源口径+防repaint确认约束,日线,姐妹交叉验证),预注册判活 · files: mining.md

- [done] 2026-07-09 · [fable] mining-round18 · 第十八轮:量子篮子横截面落后追赶(用户设想的四象限"谁落后买谁";冠军配对的全篮子推广),预注册判活;若成→观察组+量子族谱四象限图 · files: mining.md

- [done] 2026-07-09 · [fable] mining-round17 · 第十七轮:17A 板块轮动象限(QTUM RRG→QBTS,须超越在册QTUM昨日绿) + 17B SEC 424B增发事件(供给冲击否决器),预注册判活,黑马→观察组 · files: mining.md

- [done] 2026-07-09 · [fable] watch-tier-replay · 观察名单三候选(CPI+PPI公布日/周一BTC大绿日内/GPR地缘缓和)上 /factors 策略战绩「👀观察组」:replay.py tier=watch + FRED排期/GPR xls 数据源(aws deps +xlrd) + 前端分区渲染 v2.8.0 · files: backend/dashboard/replay.py, aws/requirements.txt, requirements.txt, frontend/app/factors/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json, mining.md

- [done] 2026-07-09 · [fable] mining-round16 · 第十六轮:宏观公布日溢价专题(CPI/PPI/NFP/FOMC 持有进公布,第十五轮线索;用户点单,冻结豁免;黑马→纸面马进策略战绩) · files: mining.md, 可能 backend/dashboard/qbts_paper.py+replay.py

- [done] 2026-07-09 · [fable] click-audit · 👀 按钮点击审计:Lambda _audit_click 记 IP/UA/设备提示进 publish_audit(cron不记);前端 POST 附 clientHints(时区/语言/平台/屏幕);版本号连点3次开隐藏查看窗(audit-modal,访客小结+逐条);v2.7.0 · ⚠️ 待用户跑 sql/publish_audit_migration.sql · files: aws/lambda_handlers.py, sql/publish_audit_migration.sql(new), frontend/app/_components/{audit-modal.tsx(new),control-panel.tsx}, frontend/app/_lib/data.ts, frontend/app/page.tsx, frontend/public/version.json, CLAUDE.md

- [done] 2026-07-09 · [fable] selfcheck-fixes · 修 AI 自检 6 条:①journal 日期改美东挂钟(UTC/墨尔本翻日错位)②实时报价 2× 换算差>0.8pp 主动标注基准口径③校准命中率口径说明(edge非观望 vs HOLD影子两套勿混)④新闻初筛 QUBT≠QBTS 主体消歧义⑤快照补 market_light(SPY/QQQ vs 50日线+VIX,一级信号B-1不再盲判)⑥playbook rr_veto 熔断折叠一行 · files: backend/dashboard/{journal,decision,news}.py, backend/api.py

- [done] 2026-07-09 · [fable] audit-tool · ⚖️ 8/15 审判执行器:python audit.py 一键出逐源判决报告(校准+决策台账+纸面马+扫描账本,Wilson CI 预注册规则,只读) · files: backend/dashboard/audit.py(new), audit.py(new), CLAUDE.md

- [done] 2026-07-09 · [fable] macro-event-coef · 第十五轮:宏观事件(FOMC/CPI/NFP等)×QBTS 事件日影响系数排行(FRED release dates),结果进 mining.md + 系数表接入 macro.py/决策 prompt · files: mining.md, backend/dashboard/macro.py, backend/dashboard/decision.py

- [done] 2026-07-09 · [fable] gpr-event-study · GPR 地缘风险指数×QBTS 事件研究(纯研究豁免,验证地缘雷达假设:alert日次日收益/波动是否更差),结果归档 mining.md · files: mining.md

- [done] 2026-07-09 · [fable] geo-radar · 地缘政治/政策雷达:新 backend/dashboard/geopolitics.py(Google News RSS 伊朗/川普/量子政策 + Haiku 风险分级)进 snapshot+决策 prompt;quote_handler 盘中每~30min 刷新+ntfy 高影响新条目推送;决策页新雷达卡 · files: backend/dashboard/geopolitics.py(new), backend/api.py, backend/dashboard/decision.py, aws/lambda_handlers.py, frontend/app/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json

- [done] 2026-07-08 · challenge2-cloud-bot · 千元挑战第二期:$5000 云端全自动(Alpaca paper 真挂单)。新 backend/dashboard/challenge2.py(REST 直连不加 alpaca-py;进场=challenge_basket 全场之选,87% 市价+GTC bracket,+10%触碰落袋/赢线$5500/地板$4250/30天,minute%15==2 错开SMC分钟),接 quote_handler;template.yaml+deploy-aws.yml 加 AlpacaApiKey/AlpacaSecretKey(gh secrets 已设);第一期归档 round1-2026-07 + 账户残留 LABU×3 已清(其 LIQUIDATE 实际没成交的教训:普通市价卖会被 bracket 子单锁股,须 DELETE /positions?cancel_orders=true);挑战页动态化(第N期/金额/ended/云端标注) · files: backend/dashboard/challenge2.py(new), aws/lambda_handlers.py, aws/template.yaml, .github/workflows/deploy-aws.yml, frontend/app/challenge/page.tsx, frontend/app/_lib/data.ts

- [done] 2026-07-09 · watchlist-sector-fill · 自选按轮动地图板块补空(基本面全部联网核实):+VKTX 减肥药(生科)/HIMS 远程医疗/HOOD 券商加密(金融)/ASTS 卫星通信/CELH 能量饮料(必需消费);地产+传统能源刻意留空(无干净高波动标的)。scan.py THEME 加 5 新票 + 补 FLNC 储能/OKLO 核电标签;已入 Supabase watchlist 并重扫(16 只,VKTX/HIMS/HOOD/CELH 即 买入区,ASTS 偏空回避=如预期等买点) · files: backend/dashboard/scan.py

- [done] 2026-07-08 · rotation-map-v2 · 轨迹降噪(双轴 EMA8 平滑,锯齿→蜗牛尾;avg step 0.65 vs 域±2.5)+ 前端 Catmull-Rom 贝塞尔曲线渲染 + hover 加粗聚焦;地图复用到 🔭 自选扫描页(大盘环境卡下方);线上快照已回填平滑版数据 · files: backend/dashboard/sector_rotation.py, frontend/app/_components/rotation-map.tsx, frontend/app/watch/page.tsx, frontend/public/version.json

- [done] 2026-07-08 · sector-rotation-map · 板块轮动地图(RRG 近似):新 backend/dashboard/sector_rotation.py(15 板块含⚛️QTUM vs SPY,RS=63日z、动量=RS 5日变化再标准化,每5日采样×8点轨迹)进 snapshot;前端 _components/rotation-map.tsx(四象限动效 SVG:描线动画/箭头/呼吸光晕/hover 聚焦/防碰撞标注/数据表兜底,象限四色过 dataviz 校验)挂 /challenge/lessons · files: backend/dashboard/sector_rotation.py(new), backend/api.py, frontend/app/_components/rotation-map.tsx(new), frontend/app/challenge/lessons/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json

- [done] 2026-07-07 · challenge-lessons · 千元挑战复盘页 /challenge/lessons:诚实复盘(n=2)+六条可复制纪律+今日篮子照做面板(新 backend/dashboard/challenge_basket.py 进 snapshot)+复利/赔率诚实数学;挑战页挂入口 · files: backend/dashboard/challenge_basket.py(new), backend/api.py, frontend/app/challenge/lessons/page.tsx(new), frontend/app/challenge/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json

- [done] 2026-07-07 · champs-fresh-readouts · 修AI自检发现的周一失明:①analyze_champs 信号读数(BTC/QTUM/IONQ z40/CLV/特调)提出台账幂等块外每次新算(节后无新bar时更新块跳过→prompt全空)②btc_weekend 加纯计算 weekend_signal 喂进 snapshot/决策 prompt(周一一级信号) · files: backend/dashboard/qbts_paper.py, backend/dashboard/btc_weekend.py, backend/dashboard/decision.py, backend/api.py

- [done]   2026-06-30 · nw-envelope · 新增 Nadaraya-Watson 包络(非重绘高斯核)作为又一机械判据。新建 backend/dashboard/nadaraya_watson.py(analyze_nw_envelope(df_d):因果单边核,不偷看未来→上/下/中轨+价格在包络内位置 pos+stance);接 scan.py 打分(贴近下轨pos≤0.12 +1 / 贴近上轨pos≥0.90 −1,与RSI同量级不一票独大)+卡片note;接 api.py snapshot(payload['nw_envelope'])+decision.py _build_user_msg 喂 QBTS 决策。阈值用用户TradingView的 88%/90%。⚠️给用户讲清LuxAlgo默认版重绘会灌水回测胜率,这里用非重绘版让它进纸面交易被真实验证 · files: backend/dashboard/nadaraya_watson.py(new), backend/dashboard/scan.py, backend/api.py, backend/dashboard/decision.py

- [done] 2026-06-29 · decision-chart+ev-warn · ①决策页图表:扩展现有 MiniChart(复用 lightweight-charts,不新建组件/依赖)——加 计划三线(入场/止损/目标)、SMC 供给/需求带(最近一档)、POC、历史已评判决策 ✓/✗ 标记。page.tsx 用 useMemo(chartPlan/chartMarkers,避免30s实时轮询重建图表)喂入。②交易计划卡负 EV 软警告:tradeEv()=系统自己的胜率(做空取1−p_up)×盈亏比−败率,<0 时红框提示(标注"胜率验证期,软参考")。 · files: frontend/app/_components/mini-chart.tsx, frontend/app/page.tsx

- [done] 2026-06-29 · sec-dilution-overlay · 免费 SEC EDGAR 增发/稀释叠加(补机械扫描的事件盲区)。altdata.py 加 fetch_sec_dilution(ticker):data.sec.gov submissions JSON,424B*=实际增发(high)、S-3/S-1=货架(warn);窗口分开(增发120天/货架365天);UA 要邮箱形式否则403(沿用伪域名默认,可 SEC_USER_AGENT 覆盖)。无需新表——结果挂在 scan 每张卡(scan_ticker base 加 dilution)随 watchlist_scan 持久化;decision 也喂 QBTS(refresh_decision extras + _build_user_msg 出「⚠️ SEC增发/稀释」段)。前端 ScanResult 加 dilution 类型 + watch 卡片红/橙 badge。实测 QBTS=S-3ASR货架/POET=424B5增发 · files: backend/data/altdata.py, backend/dashboard/scan.py, backend/dashboard/decision.py, backend/api.py, frontend/app/_lib/data.ts, frontend/app/watch/page.tsx, CLAUDE.md

- [done] 2026-06-29 · decision-stability+structured-output · ①(A)当日一致性护栏放在 **Supabase 支持的 journal.record()**(不是本地缓存——手机点部署站→Lambda 冷启动会清 /tmp,本地缓存抓不到她在手机上反复点的场景)。同日累计 action 存进当天 journal 记录,翻面则 decision.intraday_unstable=true 并 mutate decision→随快照发布;前端决策页行动卡下方出琥珀色横幅「今日判断不稳定→视为观望」。手机/本地/云三方共享同一 Supabase 列表 ②(B)决策改用结构化输出 output_config.format+json_schema(_DECISION_SCHEMA),去掉脆弱的正则去围栏/删尾逗号;实测 Opus4.8+thinking adaptive 通过(踩坑:etf_ticker 不能 type+enum 混用,改 enum-only) · files: backend/dashboard/decision.py, backend/dashboard/journal.py, frontend/app/_lib/data.ts, frontend/app/page.tsx

- [done] 2026-06-26 · sql-folder · 把根目录所有 *.sql(schema + 8 个 migration)统一移到 sql/ 文件夹;唯一代码引用 publish.py 注释改为 sql/supabase_schema.sql · files: sql/*(moved), publish.py

- [done] 2026-06-26 · monthly-retrospective · 月度复盘:新 backend/dashboard/retrospective.py(拉 grade_predictions 校准 + 决策台账 → 一次 Opus 写中文复盘 → 存 Supabase retrospective 表 id=current);根目录 retrospective.py 脚本 + api.py 加 /control/retrospective(本地生成)与 /dashboard/retrospective(读);前端 _components/retrospective-panel.tsx 放进历史战绩卡,按钮 2026-07-26 前锁定(显示倒计时),解锁后读 Supabase 展示;control-panel 本地加"生成复盘"按钮;data.ts 加 getRetrospective;migration: retrospective_migration.sql · files: backend/dashboard/retrospective.py(new), retrospective.py(new), backend/api.py, frontend/app/_lib/data.ts, frontend/app/_components/retrospective-panel.tsx(new), frontend/app/_components/control-panel.tsx, frontend/app/page.tsx, supabase_schema.sql, retrospective_migration.sql(new)

- [done] 2026-06-26 · mu-add+target-fix+decision-paper · ①自选扫描加 MU(存储芯片)进默认篮子+THEME ②修"上方目标"兜底:创新高/突破票上方无成交节点时不再吐低于现价的假目标(target=None,显示"已突破·上方无成交参照"),并避免污染纸面止盈 ③历史决策战绩加"模拟持仓"台账:每个方向单$1000假钱,按计划止损/目标的 ret_pct 汇总累计盈亏+当前持仓浮动(load_recent 加 paper 块,纯加法) · files: backend/dashboard/scan.py, backend/dashboard/journal.py, frontend/app/_lib/data.ts, frontend/app/page.tsx

- [done] 2026-06-26 · choch-warn+plan-declutter · ①决策页加 CHoCH 早期反转预警横幅(snap.smc.last_event.kind==='CHoCH' 时显示,纯提示不发信号,补"等BOS确认所以进场晚"的空窗) ②交易计划卡精简:默认只显示 方向+QBTZ三价+盈亏比+仓位+失效条件,把 入场条件/波动档/QBTS镜像价/杠杆说明 收进 <details>展开看细节 · files: frontend/app/page.tsx · 注:page.tsx 同时有用户未提交的响应式 WIP,未替其提交

- [done] 2026-06-25 · et-melb-annot · 决策页 ET 时间旁加注墨尔本时间(保留ET): 实时报价(asof_epoch)+经济事件(ET挂钟 date+time_et) 显示「(墨 HH:MM)」,跨日补 MM-DD。format.ts 加 etMelbSuffix/epochMelbTime,经 IANA America/New_York→Australia/Melbourne 换算(自动处理两地夏令时)。AI 简报正文里的 ET 是自由文本,无法结构化转换,保持原样 · files: frontend/app/_lib/format.ts, frontend/app/page.tsx

- [done] 2026-06-25 · tz-local-render · 决策/简报/扫描时间戳显示成本地时区: 后端改输出带时区 UTC(datetime.now(timezone.utc)),前端新增 _lib/format.ts(parseUtc 把裸时间当 UTC + fmtLocalDateTime 用本地 getter 渲染),page.tsx/watch/page.tsx/brief-panel.tsx 改用之。顺带修了「决策时效」年龄被裸时间算错~10h 的 bug · files: backend/dashboard/{decision,brief,scan}.py, frontend/app/_lib/format.ts(new), frontend/app/page.tsx, frontend/app/watch/page.tsx, frontend/app/_components/brief-panel.tsx

- [done] 2026-06-25 · scan-paper-fix · 修模拟战绩把亏损单误标「到目标止盈」: ①_exit_hint 止损判定挪到止盈前(否则下跌后浮动目标塌到现价头顶,破位被误判止盈) ②scan 结果暴露 target_num ③run_paper_trades 止盈锚定入场当天目标(pos["target"]),不再用浮动目标 · files: backend/dashboard/scan.py, backend/dashboard/scan_store.py

- [done]   2026-06-30 · smc-playbook-v2 · 升级 SMC 模块(仅 QBTS 决策页):①全局方向锁(只读日线最新结构标签 BOS/CHoCH 定多空锁)②降维中继状态机(日线锁→4h/1h 中继OB+fib0.5折价=预警→15m CHoCH+WaveTrend绿点=扣扳机)③FVG 共振入场(FVG边∩OB)+ FVG止盈磁吸(TP1)。新增 backend/data 15m 抓取(load_15m,真15m~60d)+4h重采样;新建 backend/dashboard/wavetrend.py(VMC绿点复刻 LazyBear WaveTrend);smc.py 加 build_playbook;接 api.py snapshot/decision.py prompt;前端 data.ts 类型 + page.tsx SMC 卡 playbook(锁/状态/清单✓✗/入场·止损·TP1)。自选扫描保持向后兼容不动 · files: backend/data/fetcher.py, backend/dashboard/wavetrend.py(new), backend/dashboard/smc.py, backend/api.py, backend/dashboard/decision.py, frontend/app/_lib/data.ts, frontend/app/page.tsx, CLAUDE.md

- [done]   2026-06-30 · smc-intraday-trigger · 修「一天只跑一次→扣扳机永远抓不到」:每分钟 QuoteFunction 里每 ~5min(minute%5==0,pre/regular/post)重算便宜的 SMC playbook(缓存日线/1h+force_refresh 15m,无 LLM≈$0),写进 live_quote.data['smc'],非刷新分钟 carry-forward 不闪;前端 page.tsx 优先读 live playbook+「盘中实时」脉冲徽章。TRIGGER 上升沿(prev!=TRIGGER 读回 live_quote 去重)→ ntfy.sh 推送(NTFY_TOPIC 空=不推)。新建 backend/dashboard/intraday_smc.py;quote_pusher 拆 push_payload/push_once;template.yaml 加 NtfyTopic/NtfyUrl 参数+env、QuoteFunction 1024MB/90s;deploy-aws.yml 传 NtfyTopic;data.ts LiveQuote.smc 类型 · ⚠️用户需建 GitHub Actions secret NTFY_TOPIC 并在 ntfy App 订阅 · files: backend/dashboard/intraday_smc.py(new), quote_pusher.py, aws/lambda_handlers.py, aws/template.yaml, .github/workflows/deploy-aws.yml, frontend/app/_lib/data.ts, frontend/app/page.tsx, CLAUDE.md

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

- [done] 2026-07-04 · mining-round4 · 第四轮 32 套变体回测(榜首压力测试/BTC领先/委员会扩容/LGBM等),结果归档 · files: mining.md
- [done] 2026-07-04 · btc-lead-tracker · 冠军陪跑第三匹马:BTC昨日绿×QQQ50×波目 纸面净值 · files: backend/dashboard/qbts_paper.py, frontend/app/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json
- [done] 2026-07-04 · mining-round5 · 第五轮 27 变体(VIX期限结构/52周高/TOM/FINRA短卖比/TLT),归档 · files: mining.md
- [done] 2026-07-04 · short-flow-flip · 挤空燃料模块依第五轮实证整体翻转为空头动向(偏空信号) · files: backend/dashboard/squeeze.py, backend/dashboard/strategies.py, backend/dashboard/decision.py, frontend/app/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json, mining.md
- [done] 2026-07-04 · mining-round6 · 第六轮 41 变体:在产经典策略审判(反向腿全面暴雷)+ CLV强收盘/BTC多日/迟滞带 · files: mining.md
- [done] 2026-07-04 · kill-inverted-legs+clv-horse · 在产策略反向腿静音 + CLV强收盘第四匹纸面马(v1.11) · files: backend/dashboard/strategies.py, backend/dashboard/qbts_paper.py, frontend/app/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json, mining.md
- [done] 2026-07-04 · mining-round7 · 第七轮 31 变体(执行层专题:QBTX/QBTZ衰减实测/出场工程/周一开盘周末BTC新发现),归档 · files: mining.md
- [done] 2026-07-04 · btc-weekend-signal · 周一开盘·周末BTC信号:quote_handler周一盘前算+08:00ET ntfy推送+页面横幅(v1.12) · files: backend/dashboard/btc_weekend.py(new), aws/lambda_handlers.py, frontend/app/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json
- [done] 2026-07-04 · mining-round8 · 第八轮 21 变体(隔夜BTC日频化过不了成本关/配对超涨veto与QTUM领先进观察名单/躲周末反证),归档 · files: mining.md
- [done] 2026-07-04 · veto-qtum-horses · 第五六匹纸面马:配对超涨veto + QTUM昨日绿(v1.13) · files: backend/dashboard/qbts_paper.py, frontend/app/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json, mining.md
- [done] 2026-07-06 · mining-round9 · 第九轮 %R Trend Exhaustion 专题(30 变体):日线信号稀但带骑乘吃到两波大涨,1h ▼破裂=唯一显著离场腿 · files: mining.md
- [done] 2026-07-06 · mining-round10 · 用户自改版特调指标审判(25 变体):抄底腿=十轮最强进场信号,止盈腿真能标顶,总账输在资金利用率 · files: mining.md
- [done] 2026-07-06 · v2.0-redesign · 特调双腿(⑦马+ntfy) + 决策提示词重写(十轮验证分层) + 页面iOS风重构 · files: backend/dashboard/tiaojiu.py(new), backend/dashboard/qbts_paper.py, backend/dashboard/decision.py, aws/lambda_handlers.py, frontend/app/page.tsx, frontend/app/layout.tsx, frontend/app/_lib/data.ts, frontend/public/version.json, mining.md
- [done] 2026-07-06 · mining-round11-freeze · 第十一轮姐妹票交叉验证(27变体)+ 冻结令生效(至2026-08-15) · files: mining.md
- [done] 2026-07-06 · mining-round12 · 用户实战组合审计(NW×特调,10变体):重绘欺骗81- [done] 2026-07-06 · mining-round12 · 用户实战组合审计(NW×特调,10变体):重绘欺骗81%量化,NW底部区=负alpha,特调进+NW顶出5/5 · files: mining.md
- [done] 2026-07-06 · heartbeat+cap · 每日收盘心跳推送(无信号=低优先级摘要,缺席=系统故障)+ 军规卡⓪总闸(投机仓≤总资产10%)(v2.0.1) · files: backend/dashboard/tiaojiu.py, frontend/app/page.tsx, frontend/public/version.json
2026-07-06 15:41 [session-btc-early] 周末BTC推送提前到周日20:00 ET(夜盘开门/墨尔本周一上午10点): backend/dashboard/btc_weekend.py + aws/template.yaml(SundayNightBtc调度) + page.tsx横幅文案 + version 2.0.2 [done]
2026-07-06 16:18 [session-btc-early] 第十三轮(冻结豁免纯研究): 周一信号深挖+空头终审 → mining.md [done]
2026-07-06 16:37 [session-btc-early] 会话交接归档: mining.md(实盘案例/彩票日审计/v2.0.2/交接检查点) + 记忆库更新 [done]
2026-07-07 12:53 [opus] 修AI自检#1数据问题: 周末BTC信号周一16:00 ET收盘后过期(日内单窗口关闭): btc_weekend.py [done]
2026-07-08 11:37 [fable] 进阶分析抽屉开关改成显眼的 iOS 蓝色按钮(展开深挖/收起): page.tsx + version 2.0.3 [done]
2026-07-08 11:55 [fable] 💼当前持仓功能: positions.py + pos_*动作(api.py/lambda) + decision position_advice(schema+规则16+持仓段) + PositionsCard + v2.1.0 [done]
2026-07-08 16:42 [fable] /factors 改造为🏇策略战绩页: replay.py 七马全历史复算(买卖点/收益/当前状态) + 页面重写 + nav改名 + v2.2.0 [done]
2026-07-09 10:35 [fable] 千元挑战收官打法提炼 note → mining.md(用户要求,会话收尾)[done]
