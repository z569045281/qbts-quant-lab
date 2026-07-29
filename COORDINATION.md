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

- [done] 2026-07-29 · [opus] event-day · 用户点单复盘"为什么周一 +40% 没让我买":先立预注册线再跑数,**三个候选全部判死**(A 极端跳空当买信号:QBTS ≥8% 中位 −0.00%、姐妹 IONQ −0.87%/RGTI −2.35% 反向;B 暴涨次日日内空:胜率 56%<60%、t=−0.33、IONQ 反向 +3.89%;D 暴涨日收盘买次日卖:QBTS 单独 n=59 +5.33% t=+2.73 p=0.008 近1年不反号、**七条过六条**,只栽在姐妹 0/2 同向 —— 看到结果后不改线)。**唯一真发现**:技术面在极端跳空档统计失效 —— 跳空 3~8% 档 t=−2.02/p=0.045 有效,**≥8% 档 t=+0.36/p=0.722 无分辨力**;07-26 那晚的错误就是把 3~8% 的负期望套到 +10.2% 的跳空上。落地为**熔断器**非信号:新 `backend/dashboard/event_day.py`(|跳空|≥8% 实时价优先 / 催化剂 breaking → `technical_muted`),三出口=决策 prompt 强制段(禁拿跳空/超卖/均线劝进劝退·允许方向留白·禁因"涨太多"转做空)+ 分钟级 ntfy(纯本地算吃 change_pct、不挑槽位、push_key 每日去重)+ 前端橙卡(live 优先)。**不改任何已有读数数值**(预注册条件)。28 条测试全绿(ntfy 打桩)、tsc 通过、07-27 真实回放命中 +10.2% 而 07-24 不命中。⚠️ 需 push 触发 Deploy AWS jobs + Pages。files: backend/dashboard/event_day.py(new), backend/api.py, backend/dashboard/decision.py, aws/lambda_handlers.py, frontend/app/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json(2.27.0), mining.md, docs/SIGNALS.md, docs/LESSONS.md

- [done] 2026-07-29 · [opus] fix-staleness · 四修(全部完成,tsc 通过,8 条缓存判定用例 + 端到端验证):①Vivienne 卡裸日期(渲染 as_of 却读起来像生成时间)②load_or_fetch 24h TTL 与日线更新节奏错配(09:02 写的缓存 21:33 读仍算"新鲜",内容却是前一交易日)③加周日 20:05 ET 决策 cron(夜盘开门=BTC周日UTC线定案,墨尔本周一 10:05)④docs/SIGNALS.md 补 catalyst_radar。files: frontend/app/page.tsx, frontend/public/version.json, backend/data/fetcher.py, aws/template.yaml, docs/SIGNALS.md

- [done] 2026-07-28 · [opus] catalyst-radar · 📣 公司催化剂雷达(用户点单:"昨天暴涨和大新闻关系挺大,改成和政治雷达一样的实时监测+ntfy"):新 backend/dashboard/catalyst_radar.py 照 geopolitics.py 同构(Google News RSS 免费无 key,`when:1d` 比地缘的 2d 窄——催化剂讲时效 → 一次 Haiku 分级 → 盘中 `minute%10==3` 刷新 + ntfy + 去重冷却 + off-tick carry-forward),两条 track:D-Wave/QBTS 自身公告、量子板块同行。**槽位不撞**:3/13/23/33/43/53 对 5 取模恒 3、对 15 ∈{3,8,13}、对 30 ∈{3,13,23},避开 %5==0(SMC)/%5==4(游击出场)/%15==2(挑战)/%30==8(地缘)。**prompt 两条硬规则**:①描述价格结果的标题("QBTS 暴涨20%该不该买")不是催化剂一律 low——要因不要果 ②同一件事多家转载只留最原始那条 high。**实测**(07-27 真实新闻,一次 Haiku):17 条抓到 1 high(AT&T 签约)/1 medium/15 low,12 条转载稿全被判 low「重复报道」→ 只响一次铃。**故事级去重踩坑**:首版用整体 token Jaccard≥0.6,实测两条讲同一笔 AT&T 交易的标题只有 0.2(同一件事的不同报道共享的是**专名**,动词框架全不同),且 `[a-z0-9]+` 会把 "AT&T" 切成 at+t 双双出局——改成「剔掉每条 QBTS 新闻都有的词(qbts/wave/quantum/soars/deal…)后共享任一专名即同一故事」+ `&` 保留在词内,用 07-27 真抓到的 6 条转载 + 3 条不同事件验证 9/9 正确。冷却:升 breaking 立推 / 同级别不同故事 45min / 降级不推(公司消息"没新消息"不值得响铃,与地缘缓和不同)。**零决策权**不进 edge(news.py 已占 _NEWS_WEIGHT=0.15,同一消息面不计两次),只进 snapshot + 决策 prompt 事件背景段(breaking 时明示"技术面读数在事件驱动日解释力下降")。前端决策页 §4.5 新卡(照地缘卡同构,low 全滤掉免得淹掉真催化剂)+ data.ts 类型 + tsc 通过 + v2.26.0。验证:8 推送分支 + 2 守卫打桩(ntfy/RSS/Haiku 全桩不花钱)、9 去重用例、端到端 prompt 渲染。⚠️ 需 push 触发 Deploy AWS jobs + Pages。files: backend/dashboard/catalyst_radar.py(new), aws/lambda_handlers.py, backend/api.py, backend/dashboard/decision.py, frontend/app/_lib/data.ts, frontend/app/page.tsx, frontend/public/version.json

- [done] 2026-07-28 · [opus] selfcheck-0728 · AI自检07-28四条,三修一待拍板:**②量比错标**(intraday.py `surge_ratio` 实为"末60分钟 vs 当日自身均速",按当日自我归一化→结构上看不见日级放量;07-27 全天 2.62×天量它仍输出 0.93 并盖章"正常区间")→ 显示改「末60分 X× 当日均速」+ 新增真·量比 `day_vol_ratio`(当日/前20日均量),实测复现修前修后字符串,signal/confidence 零变化。**①④价格基准混用**(同一个 payload 里两个"今天":日线派生读数全基于 as_of 收盘 $16.21,实时价 $19.51,背离+20.4%,"折价区3%/快%R−97.9"被当现值)→ 查明根因是 `_LIVE_QUOTE_CACHE` **只有本地 `/quote/live` 会填**,云端 publish 从不走那条路 + `refresh_decision` 里 snapshot 排在 quote_live **之前** → 线上 `_live_px` 恒 None。**刻意没改信号行为**(让 live_price 真流进 SMC/POC 会在 8/15 测量窗内改被评判信号的输入,已交用户拍板),改为 decision.py 新增 `_price_basis_note` 在 prompt 里摊开两个基准、背离≥3% 明令"派生读数不得当现值采信、只作结构参照"(4 用例:大背离/正常/无实时价/反向背离,并用线上真实快照端到端验证)。**④的另一半**:selfcheck.py 那条"价格段vs量能段>2pp=不同步"确定性规则本身误报(比的是 as_of bar 涨跌 vs 当前 session 涨跌,日线缓存落后时本就是两天)→ 加 `session == as_of MM-DD` 同日门,4 回归用例(误报场景不报/真错位仍报/一致不报/老快照无session不报)。**用户随后拍板两项,已落地**:(a)**接通实时价**——新 `api.py::_live_price_for_snapshot()` 进程内缓存拿不到就回读 Supabase live_quote,>20min 陈价一律退回 None 用收盘价(陈价会假装自己是"现在",比收盘价更糟);`analyze_nw_envelope` 加 `live_price` 参数但**只替换位置判定、带子仍由收盘构建**(拿盘中价重跑核回归=repainting,违背该非重绘移植版的存在意义),新增 `price_basis`/`close_px` 字段;两个老调用点只传 df_d 不受影响;4 用例(无实时价/跌进买入区/冲进卖出区/区间中部)+ 断言带子不随实时价漂移。`_price_basis_note` 改成「已用实时价」vs「仍是收盘口径」两类分别交代。⚠️ 这改变了 8/15 受审信号(SMC playbook 还驱动 ntfy TRIGGER)的输入,审判须分代看。(b)**③同行落后追赶并入收盘心跳**(不新开 ntfy 通道,避免重蹈一晚20条轰炸):tiaojiu.py `maybe_tiaojiu_push` 复用 `analyze_relative_strength` 的 `catchup_triggered`,单独触发→high 响铃,与特调抄底同日→共振行,与止盈同日→明说两腿方向相反不替用户消歧义,都不触发→心跳多一行"追赶未触发";**每交易日推送条数不变(仍是 1 条)**;8 分支打桩验证(5 信号分支 + 非窗口/周末/去重三守卫)。无前端改动→未升 version.json。⚠️ 后端改动需 push 触发 "Deploy AWS jobs" 才到云端。files: backend/dashboard/intraday.py, backend/dashboard/decision.py, backend/dashboard/selfcheck.py, backend/dashboard/nadaraya_watson.py, backend/dashboard/tiaojiu.py, backend/api.py, CLAUDE.md
- [done] 2026-07-27 · [opus] docs-taskmap · 用户点单:CLAUDE.md/mining.md 太乱 → 重构成「任务地图」式。CLAUDE.md 480→77 行(任务地图表 + 多会话协作 + 永远适用的铁律 + 记忆库指针),正文按主题拆进 **docs/ 14 份**(ARCHITECTURE/DEPLOY/SECRETS/AWS-LAMBDA/MARKET-DATA/SUPABASE/DECISION/SMC-PLAYBOOK/SIGNALS/AUDIT-AND-EDGE/SURFACES/CHALLENGE/SPACEX/LESSONS)。**零事实删除**(80 个特征 token 全量比对 + 链接全通);顺带把散在各处的 QuoteFunction 分钟槽位整理成一张表、secrets 接线四件套成一张表。mining.md 加「怎么用这份档案」+ 27 轮索引表(含重复编号 22/22B 的标注)。files: CLAUDE.md, mining.md, docs/**(new)

- [done] 2026-07-24 · [opus] decision-parallel · 出决策慢诊断+修:主决策(Fable adaptive思考+16k)与 DeepSeek 影子决策(推理模型,实测小prompt都12.9s→全量30-60s)原本串行,墙钟=两者相加。影子零决策权却让用户干等。修:get_or_generate_decision 里把 generate_shadow_decision 丢进 ThreadPoolExecutor 与 generate_decision 并发,墙钟从 sum 变 max。决策内容/影子记账/缓存/journal 零变化,纯延迟优化。files: backend/dashboard/decision.py

- [done] 2026-07-24 · [fable] audit-breakeven · 审判器保本线修正(用户拍板"按修正版落地"):audit.py 判决线从一刀切 0.5 改为各池自己代码承诺的保本胜率 p*=1/(1+RR_design)(扫描v2 1.5R→0.40 / 游击战 2.5R→0.286 / 方向单按各单 rr_ratio),方向表态类(edge逐源/daily_call/影子/HOLD)保持 0.5;期望R只做展示列不做判决;预注册修订注记(2026-07-24,依据=设计常数矛盾非结果不满意),报告新旧两线并排。scan_paper 按 epoch 分池(CLAUDE.md 承诺过的"审判按 epoch 分开统计"此前没落地)。纯 audit 层只读改动。files: backend/dashboard/audit.py, CLAUDE.md

- [done] 2026-07-23 · [opus] selfcheck-0723 · AI自检07-23四条,两查证两修:①初请失业金"已发布未回填"×2(决策模型+全站体检各报一次)=**非bug,结构性时序**:08:30 ET 发布 vs 09:00 ET publish,FRED 要几小时才更新;实测 5h 后 FRED 已出 187K 且 enrich_actuals 正确回填,下次 publish 自愈,decision.py 07-14 起已显式标注"严禁拿前值当今日值"→ 风险已处置。修:selfcheck prompt 加"actual空+hours_until≥−6h=正常时序,别每周四报一次"。②"连续10日HOLD错过15%跌幅,建议放宽特调到盘中预警"—— 事实前提对(实测 $20.09→$17.10 = −14.9%,12条全HOLD),但**药方有逻辑硬伤**:特调抄底是多头进场腿,放宽它抓不到下跌;且反事实实测——这11天特调一直在蹲守区却从未收盘确认,若按"蹲守即进"会在 07-09 $21.16 买入→今日 $17.10 = **−19.2%**,正是收盘确认过滤器的价值(与第二十五轮互证)。做空腿四轮判死不复活。漏判已由昨日 HOLD 判读台账记录(07-10/12/13/15 均 ✗),8/15 凭累积数据重定阈值,不中途凭 n=1 松绑已验证扳机。③全站体检把一条自己写着"计算相符…恒等式验证通过,无矛盾"的项填进 findings = 纯噪声 → prompt 明令"自证无矛盾一律不输出"+**代码层兜底** `_is_nonfinding` 过滤(昨日教训:确定性判断不能只靠LLM合规),4用例验证真矛盾保留/伪发现丢弃。files: backend/dashboard/selfcheck.py

- [done] 2026-07-22 · [opus] selfcheck-0722c · AI自检07-22三批两修:①8-K item 3.01 模糊标签(07-20只加了"须查原文"的免责说明=把判断推给读者,不算修)→ 新 `_classify_301` 抓 filing 原文正文关键词自动定性(自愿转板 info / 合规缺陷 high / 判不出退回warn),只对 3.01 多打一次 HTTP(该 item 稀有)。**实测坐实**:07-14 那份被挂 warn 8 天的其实是**自愿**转 Nasdaq(7/24 NYSE 停牌→7/27 Nasdaq 开盘,代码不变),完全中性。⚠️首版栽了一跤:SEC 标准条目抬头本身含 "failure to satisfy"(所有3.01通用模板),关键词撞上模板把自愿转板误判 high → 必须先剥抬头再匹配,已加三方向回归用例(真不合规/自愿/模糊)全过。②新闻"QBTS/IONQ/RGTI合计抛售$988M"多票聚合口径对单票无信息量→ 新 `fetch_insider_form4` 直取本票 Form 4 非衍生 code='S'(只算公开市场卖出,排除M行权/A授予)+ yfinance float 算占比:**实测 QBTS 自身近60天 $35.4M / 占流通 0.57%**(与$988M观感天差地别,主要是 CEO/CFO),接 snapshot extras + 决策 prompt 新「👤 内部人卖出」段并明文纪律"遇多票聚合数字一律以本票口径为准"。files: backend/data/altdata.py, backend/api.py, backend/dashboard/decision.py

- [done] 2026-07-22 · [opus] guerrilla-serverside · 🎯 游击战改服务端自算(用户改口"webhook和TV都不需要,触发发ntfy就行"):删掉整条 webhook 层(api.py /hooks 端点、lambda module 路由、template ErHookSecret、deploy ER_PARAM 全移除),改 guerrilla.py 三条件服务端自算:A 日线 wt1<-70(wavetrend同参,实测4.4%天数) B 连续两日 Intrabar POC(15m~26根/日 volume-at-price 重构)重合≤$0.05 C RR≥2.5(target=上方最近历史POC墙/无则50日高)。maybe_guerrilla_signal 收盘后16:05-20:00 ET每日算一次(meta.last_compute_date去重)命中→ntfy+开仓;check_exits/冷却/ledger machinery 全复用。真实数据实测未命中(wt1-64>-70/POC gap 0.10>0.05,读数如实)+假SB全生命周期7步过(命中/去重/非窗口/结算$85.39/冷却武装/冷却期拒开)。无dangling ref+tsc通过。前端卡文案改"收盘自算",v2.25.1。⚠️待用户只剩一步:跑sql/guerrilla_migration.sql(ER_HOOK_SECRET/TV告警不再需要)。files: backend/dashboard/guerrilla.py, backend/api.py, aws/lambda_handlers.py, aws/template.yaml, .github/workflows/deploy-aws.yml, frontend/app/factors/page.tsx, frontend/public/version.json, CLAUDE.md
- [done] 2026-07-22 · [fable] guerrilla-module · 🎯 极度超卖游击战(用户点单"弄吧,放到策略战绩里"):TV Pine webhook 驱动的高危观察模块,零决策权$1000/枪纸面。新 backend/dashboard/guerrilla.py(on_signal:secret→bar_ts幂等去重→24h冷却锁fail-CLOSED→开仓;check_exits:minute%5==4只在有仓时拉1m行情,触stop/target按触发价结算→ledger→平仓武装冷却;epoch为真理全存Supabase防/tmp清空)。路由:Lambda publish_handler 按 body module 识别(TV无自定义header→secret走?key=,空=模块关,不进点击审计)+api.py本地端点。template.yaml ErHookSecret+deploy-aws.yml ER_PARAM。前端/factors新GuerrillaCard(冷却❄️/在场/流水,表缺=不渲染)v2.25.0。假SB全生命周期8项测试过(dedup/冷却拒信/几何校验/结算数学$85.39✓)。⚠️待用户:跑sql/guerrilla_migration.sql + 设ER_HOOK_SECRET(GitHub secret+.env) + TV告警指向Function URL?key=。files: backend/dashboard/guerrilla.py(new), backend/api.py, aws/lambda_handlers.py, aws/template.yaml, .github/workflows/deploy-aws.yml, sql/guerrilla_migration.sql(new,gitignored), frontend/app/_lib/data.ts, frontend/app/factors/page.tsx, frontend/public/version.json, CLAUDE.md

- [done] 2026-07-22 · [fable] mining-r27-streaks · 第二十七轮(用户点单):"连涨几天必大跌/跌一周下周涨"猜想审判——连涨/连跌N天(3/4/5)fwd + 连涨后5日内大跌概率 + 周维度反转(上周负→本周) 预注册;判活须 |t|≥2 且 n≥15 且中位过基线 且对在册 RSI2/特调/5日新低 有增量;做空腿即使显著也只作观察(判死家族不复活) · files: mining.md

- [done] 2026-07-22 · [fable] mining-r26-intrabar · 第二十六轮(用户点单,冻结豁免):Intrabar 画像回测——净delta≥+40%/突破接受判读/绿日+高delta 三个预注册变体的 fwd1/3/5,判活须 |t|≥2 且胜均过基线;过判活也只进观察组不直接当买信号 · files: mining.md

- [done] 2026-07-22 · [fable] selfcheck-0722b · AI自检07-22第二批四查:①期权"数据缺失"=Yahoo把全链OI置0(OCC断供,volume正常,实测3到期日vol全有OI全0)→options.py 加降级口径:OI断供时退回纯PCR_vol读数(权重压0.10/confidence low/口径诚实标注"仅当日量能"),不再整体拉黑②财报日期未获取=预期中的时序(用户昨晚才跑迁移,晚于周二publish)→本地跑sync_earnings_dates验证+预播种成功(下次财报2026-08-06,15天后),今日09:00 ET publish自愈③挑战"equity+pnl≠sleeve_start差271.26"=Haiku自创错误恒等式且算术都错(真恒等式pnl=equity−sleeve_start分毫不差)→确定性代数下沉规则层(_check_challenge加|pnl−(equity−start)|>1检查,同07-16跨页价格教训),digest加pos_value直给持仓市值,prompt明文禁止自创公式④13F滞后113天建议缩短间隔=拒绝:13F按SEC法规季度申报,数据不存在没法更频繁拉;衰减到零正是07-13修复在正常工作(拦住18%命中的假日频看多信号),Q2申报窗8/14截止后自然更新。files: backend/dashboard/options.py, backend/dashboard/selfcheck.py
- [done] 2026-07-22 · [fable] waiting-for-card · ⏳「今天在等什么」卡(用户:"天天观望不知道在等什么"):新 backend/dashboard/waiting_for.py 六个一级扳机(特调抄底/RSI2/同行追赶/周末BTC/z40配对/crypto顺风)当前读数+距触发距离,纯展示复用 snapshot 现成读数零新拉取不进决策权重;api.py payload["waiting_for"];前端决策页历史战绩上方新卡(🟢已触发/⚪待触发/⏸不适用+risk_off降档警示)v2.24.0。真实数据实测:特调蹲守狙击区"收盘≥$18.16即触发"直接可见。files: backend/dashboard/waiting_for.py(new), backend/api.py, frontend/app/_lib/data.ts, frontend/app/page.tsx, frontend/public/version.json, CLAUDE.md
- [done] 2026-07-22 · [fable] hold-grading · HOLD 判读入台账(用户拍板"当天涨幅>5% 观望就是错的,就是亏钱"):journal.grade_pending 给 HOLD 打 correct——决策覆盖日 |QBTS|≥3% = 漏判✗(复用 audit.py 07-13 预注册口径,>5% 被更严 3% 覆盖不设第二标准)+day0_ret_pct+漏判 Haiku 反思(HOLD 专用措辞)。方向单/观望分池:load_recent 出 hold_accuracy,accuracy 按 action 显式过滤;_lean 按 action 分流(journal+retrospective 两处同修——今天 calibration 教训的直接应用:改字段语义必须 grep 全部读者,audit.py 已有 action 过滤天然安全,scan_store 是独立店无关)。回填 23 条历史 HOLD:12✓/11✗(48% 漏判)已写 Supabase。决策 prompt 历史行漏判显示「当日±X%(≥3%,漏判——观望不是免费的)」;前端观望判读 chip+✗漏判行 v2.23.0。合成数据+真实台账+tsc 全验证。files: backend/dashboard/journal.py, backend/dashboard/decision.py, backend/dashboard/retrospective.py, frontend/app/_lib/data.ts, frontend/app/page.tsx, frontend/public/version.json, CLAUDE.md
- [done] 2026-07-22 · [opus] overnight-quotes · 🌙 夜盘行情补盲(用户:办公室Win10 24/7跑夜盘轮询)。第0步先探——用现有Alpaca key 试 `feed=overnight` **直接成功**(QBTS夜盘实时bid/ask,免费档),**整台Win10+Tailscale方案省掉**,云端加一段即可。实现:quote_pusher.py fetch_overnight(取bid/ask**中点**非稀疏最后成交——QBTZ实测印过19h陈价$6.49而中点$5.83才对)+_overnight_window时钟门+QBTS mark≤20min判活跃→session=overnight;build_payload仅closed且夜盘窗时打Alpaca(白天零改动零延迟)。template.yaml QuoteFunction原调度只04:00-19:59+周日晚,夜盘窗根本不跑→加OvernightEvening(*20-23 MON-THU)+OvernightMorning(*0-3 MON-FRI)。challenge2已自门控9:30-16:00夜盘不误交易。前端SESSION_BADGE.overnight🌙徽章+LiveQuoteEntry加ov_*字段+v2.22.0。夜盘价只展示不驱动信号(薄流动性UNPROVEN)。本地--once实测session=overnight/QBTS$17.91(+7.12%)已回读Supabase确认,tsc通过。files: quote_pusher.py, aws/template.yaml, frontend/app/_lib/data.ts, frontend/app/page.tsx, frontend/public/version.json, CLAUDE.md
- [done] 2026-07-22 · [fable] hold-cost-feedback · 用户追问"系统为什么错过QBTZ+92%"全面复查,四根因:①v1元模型下跌段15天喊BUY(07-02→07-16崩盘12天里11天BUY,mining.md第二十四轮已判死,07-17 v2已替换——v2三天全SELL方向正确)②唯一空单止损过紧被洗(本日已修regime-floor)③一级信号库零空头进场腿=设计使然非bug(第七/九/十/二十三轮反复判死做空QBTS全部路径,空腿11笔2胜−99%;bear lock=别做多的过滤器不是做空扳机;QBTZ这波+92%是2年样本唯一像样空头行情n=1,不推翻分布)④负反馈回路:台账天天给模型看✗−10.4%教训却从不展示连续观望走掉的行情,单向教"动=亏"。本次修④:decision.py 历史战绩段加「连续观望成本」(连续≥3天HOLD且期间|QBTS|≥8%→强制要求模型在summary正面回答为什么不参与)+「表态与行动背离」(连续≥3天同向bold_call却全HOLD→要求解释或老实拉回0.50),真实数据验证12天HOLD/−17.3%正确触发。③按记忆qbtz-short-fomo锚定第二十三轮不重推演,不复活判死家族。files: backend/dashboard/decision.py
- [done] 2026-07-22 · [fable] regime-stop-floor · 用户质疑"21天20次HOLD、QBTZ却3.5→6.8涨92%,系统死了吗"→查真实台账坐实:唯一一次方向单(06-25 SHORT_QBTZ,信心6)止损设在entry+$2.65(≈1.03×ATR14),而当天regime模块自己算出的是expansion/87百分位(prompt里已写"需≥1.5×ATR")——止损太紧2天后被反弹洗出(−10.45%),此后价格再未回到旧止损上方,若按1.5×ATR($25.42)本该扛住反弹吃到目标+13.5%。根因=regime.stop_hint只是prompt里的散文提示,无代码强制。修复:_sanitize_decision 新增 regime-floor 硬约束(expansion regime 用 1.5×ATR、其余 1.0×ATR,取当日真实atr_pct×现价,模型止损低于此地板则代码强制拉宽),用真实06-25数据+两个合成回归用例验证(24.2→25.42;已够宽的止损不动;正常regime过紧止损→1×ATR)。纯后端数值护栏,无新字段/无schema变动/无前端改动。files: backend/dashboard/decision.py
- [done] 2026-07-22 · [fable] selfcheck-0722 · AI自检07-22三查:①财报日历云端持久化(07-21已修)确认待用户跑 sql/earnings_calendar_migration.sql,非新bug②SMC find_sweeps note 只写被扫旧swing的日期、没写扫单当天日期,易误读成"旧位当前参照"→ 补扫单日期前缀③重大发现:calibration.py grade_predictions 从不读 model 标签,v1(07-17停用)陈年数据混进"25条23%命中"顶替v2汇报,实测v2真实n_graded=1(部分窗口)——grade_predictions 加 model="v2" 默认过滤,audit.py 报告分离展示v1历史存档(不参与判决)。CLAUDE.md 教训归档。files: backend/dashboard/calibration.py, backend/dashboard/smc.py, backend/dashboard/audit.py, CLAUDE.md

- [done] 2026-07-21 · [fable] v1-inverse-shadow · v1反向影子(用户拍板,承AI自检建议):edge.py 重构出 `_build_contributions` 共用+新 `compute_edge_v1`(逐字节复现原始v1:无上限裸加+无regime+EV±1%阈值,compute_edge/v2行为不变,已用合成快照验证 v1/v2 分歧符合mining.md记录的病征)→ decision.py `_invert_v1_shadow` 把v1表态整体倒过来当零决策权影子(纯机械$0)→ journal.py record/grade_pending 加 v1inv_bold_call 同一套fwd5评分 → audit.py ②🥊 三行同框。CLAUDE.md 已归档。files: backend/dashboard/edge.py, backend/api.py, backend/dashboard/decision.py, backend/dashboard/journal.py, backend/dashboard/audit.py, CLAUDE.md

- [done] 2026-07-21 · [fable] selfcheck-0721 · AI自检07-21两修:①volume_profile.py `_action_hint` VAL/VAH fallback 未判方向,价格深跌到VAL下方时会把"跌破X下看"指向一个更高的VAL(方向倒挂假话)——加"是否真在磁吸位更远侧"判断,不成立就说"暂无更多参照"②财报日历云端数据源失败=Lambda/tmp冷启动清空本地parquet缓存(与finra_short同病)→ 镜像 sync_short_volume 套路新增 sync_earnings_dates,接入 publish.py + lambda_handlers.py,新表 sql/earnings_calendar_migration.sql(待用户跑)。元模型19%命中率转inverse-weight影子跟踪的建议留给用户拍板,未动手实现。files: backend/dashboard/volume_profile.py, backend/data/altdata.py, publish.py, aws/lambda_handlers.py, sql/earnings_calendar_migration.sql(new)

- [active] 2026-07-21 · [fable] challenge2-resume · 千元挑战二期三连亏(LABU/WEBL/LABU 全负,两次触地板)复盘+恢复运行(用户拍板):①诊断=扫描器对大盘环境全盲,三笔都买在动量榜首却撞 risk_off 回撤②修复=复用 scan.py `_market_context` risk_off 闸门③用户选择取消地板跑到8/15(非重设)④顺带修 _finish() halt路径 pnl 从不重算的陈旧显示bug。floor_line 改 nullable 贯穿 backend+frontend。files: backend/dashboard/challenge2.py, backend/dashboard/selfcheck.py, frontend/app/_lib/data.ts, frontend/app/challenge/page.tsx, frontend/public/version.json

- [done] 2026-07-20 · [opus] intrabar-profile · 新增 Intrabar Profile 辅助卡(用户点单,仿 Kioseff TradingView editor's pick):用日内 1h 子bar 重构最近日线bar 内部的成交量画像+签名delta(吸收/投降/派发读数),回答"价格到需求区时买盘在吸收还是继续投降"。地图非信号——不进 edge/机械打分,只展示+喂决策prompt作确认腿参考(同 POC/NW 待遇)。files: backend/dashboard/intrabar_profile.py(new), backend/api.py, backend/dashboard/decision.py, frontend/app/_lib/data.ts, frontend/app/page.tsx, frontend/public/version.json

- [done] 2026-07-20 · [fable] tiaojiu-exec-timing · 第二十五轮(用户点单,冻结豁免):特调抄底腿执行口径回测——盘中上穿即进(预挂单,吃假突破) vs 收盘确认进(现行,每次买贵),同出场规则隔离执行差;结论定该挂单还是等收盘 · files: mining.md

- [done] 2026-07-20 · [fable] selfcheck-0720 · AI自检07-20四查:①13F措辞矛盾(decision.py陈旧标注改用active_report_date对齐holdings口径)②8-K 3.01标签补"不分自愿换所/被迫退市"③财报日历段缺失时显式标注数据缺口+补倒计时④全站体检挑战页误报(digest补in_position/sleeve_start,空仓+已实现亏损≠矛盾);特调盘中vs收盘回测建议因挖矿冻结令待用户拍板 · files: backend/dashboard/decision.py, backend/data/altdata.py, backend/dashboard/selfcheck.py

- [done] 2026-07-13 · [fable] scan-mech-v2 · 自选扫描买卖机制六连修(用户点单"全修"):P0 盈亏比门(目标须≥1.5×止损距离,不合格往上找磁吸)+P0 模拟器改回踩限价单(照卡片打法,5日有效期)+P1 买入区改顺风×回踩合取+P1 板块轮动象限门(左半边降级)+P2 避雷横幅+P2 无目标仓位破10日线跟踪出场;账本 epoch 划线 v2,旧仓按新出场规则跑完 · files: backend/dashboard/scan.py, backend/dashboard/scan_store.py, frontend/app/watch/page.tsx, frontend/app/_lib/data.ts, frontend/public/version.json, CLAUDE.md

- [done] 2026-07-10 · [fable] mining-round22 · 第二十二轮:周末信息→周一 系统性专题(用户点单,冻结豁免纯研究)。预注册四候选:A 纳指期货周日夜盘(NQ=F 1h) B 亚洲周一领先(N225/HSI,美开盘前收盘) C ETH周末对BTC周末的增量 D 金价周日夜盘避险读数;判活=|t|≥2 且对在册周末BTC有增量 且姐妹≥2/3 同向;赢家最多进观察名单 · files: mining.md

- [done] 2026-07-09 · [fable] mining-round21 · 第二十一轮(挖矿收官):Google Trends 散户搜索热度(pytrends 周频 SVI,预注册:n<10 只作文字;诊断镜子假说) · files: mining.md

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
2026-07-10 09:05 [fable] 地缘雷达推送频控(一晚20条轰炸修复): geopolitics.py maybe_geo_refresh 加冷却(升级立推/同级3h/降级1h,last_push_ts随live_quote) + CLAUDE.md [done]
2026-07-10 10:45 [fable] 千元挑战二期改马拉松(用户改规则): challenge2.py 取消+10%判赢收手→跑到8/15+里程碑推送+平仓日冷却+equity_curve / challenge页SVG资金曲线 + v2.9.0 [done]
2026-07-10 11:20 [fable] 适用域研究(用户提问:这套仪表盘适合分析什么股): 5核心信号×5股性篮子横扫回测 → mining.md 归档,纯研究零部署
2026-07-10 12:40 [fable] 观察组第4号候选上线(用户拍板): replay.py obs_levmr 杠杆ETF超卖回归(NW买线下穿·持10日·单仓) + factors页/data.ts sym字段 + v2.10.0 [done]
2026-07-10 13:10 [fable] obs_levmr 口径修正: FNGU 短历史(2025-02起)截短交集日历致全期虚高 → 剔出宇宙(5只完整2y票),全期+127%/近1年+185% 诚实分窗 [done]
2026-07-10 15:50 [fable] AI自检07-10三连修: news时间戳UTC→ET / QBTX·QBTZ隐含公允价+折溢价(quote_pusher)+失效价换算锚改公允(decision._anchor_prices) / rel_strength补姐妹单日+追赶触发判定+peers TTL刷新+滞后守卫 [done]
2026-07-13 14:05 [fable] 定投菜单补全(用户:都加): dca.py +AVDV(股80: 30/20/14/8/8)+压舱石档BND 12/GLDM 8(ballast_etfs卡片+权重,deploy改固定比例不择时) + dca页压舱石卡片区/7色权重条/计算器并入压舱石 + v2.12.0 [done]
2026-07-13 16:05 [fable] 仪表盘回测审计三连修(用户:1/3/4都修): holdings.py 13F陈旧度闸(主动持有人报告期,75/120天衰减静音)+Vanguard/Geode误分类修 + audit.py HOLD判读(|当日|<3%=对,预注册)+纸面马补买入持有对照 + CLAUDE.md教训 [done]
2026-07-13 17:20 [fable] 大胆预测可测量(用户反省:整月观望回测无意义): decision.py 必填 bold_call_5d(up/down 强制二选一,与action解耦)+sanitize兜底 / journal 影子分优先用它 / audit ②段新增每日方向表态+p_up骑墙率 / 决策卡押涨押跌章 + v2.13.0 [done]
2026-07-13 18:10 [fable] SMC需求侧盲区修复(用户TV对比暴露): find_order_blocks 弃[-4:]改全事件扫描,未回补OB不论新旧保留 → 5/19需求OB $17.74-18.77 回归(=用户LuxAlgo蓝带) [done]
2026-07-13 18:55 [fable] 第二十二轮(用户点名): 供需区买卖回测 → 无晋升,FVG触碰=接刀第三证,阻力卖会卖飞,V5往返+270%是彩票幻觉 → mining.md [done]
2026-07-13 19:40 [fable] AI自检07-12三连修: 地缘alert×盘面risk_on交叉验证注 / 持仓天数改ET日期(UTC虚高1天影响军规) / 周末报价跨日标注'上一交易日' + 持仓现价隐含公允价口径标签 [done]
2026-07-13 20:50 [fable] DeepSeek影子考场(用户要求Claude/DeepSeek切换): decision.py generate_shadow_decision(V4 Pro同prompt,零决策权,shadow_ds字段) / journal ds_bold_call+统一fwd5评分 / audit 🥊表态两行 / 决策卡切换UI + DEEPSEEK_API_KEY全链路接线 + v2.14.0 [done]
2026-07-13 21:30 [fable] 交易计划卡加同卷对照区块(用户要求): 另一模型的独立判断常驻显示(方向/信心/押注/ETF三价/RR/仓位/入场条件+同向分歧章),随切换互换 + v2.14.1 [done]
2026-07-13 21:55 [fable] 决策存档补全(用户:都要存好之后回测): journal 增 ds_action/conviction/entry/stop/target 结构化字段;确认 dashboard_state 全快照永久累积(81行) [done]
2026-07-13 22:40 [opus] SpaceX第二仪表盘(用户:只用deepseek不用fable): backend/dashboard/spacex.py 自包含DeepSeek-only决策(BUY/HOLD/REDUCE,自抓yf+GoogleNews+事件日历,薄数据守卫,无key降级None不回退Claude) + sql/spacex_migration.sql(待用户跑) + publish.py §4.7 + frontend /spacex页/nav🚀/data.ts类型 + v2.15.0 [done]
2026-07-13 23:20 [opus] SpaceX单独重跑按钮(用户:加个单独跑spacex的按钮): lambda_handlers action='spacex'分支+每日publish带上SpaceX / api.py /scan/watch同分支 / data.ts postSpacexRefresh / /spacex页🔄按钮(WATCH_EDITABLE门,30-60s spinner) + v2.15.1;表已建,本地写入回读确认(data/news/catalysts落库,decision云端填) [done]
2026-07-13 23:55 [opus] SpaceX抢先量三条腿(用户:三条腿都加): spacex.py fetch_spacex_options(ATM跨式预期波动/IV期限结构/事件溢价/偏斜)+fetch_spacex_intraday(1h~130根RSI/ATR/均线/VWAP)+fetch_spacex_peer_prior(太空同业1年历史收缩估计) 全喂进DeepSeek prompt / 前端/spacex三彩色区块+data.ts类型 / 日线RSI73失真vs盘中RSI27对比 + v2.16.0;本地写入回读确认三腿落库 [done]
2026-07-14 [opus] AI自检07-14两连修: VIX双源打架(rel_strength改用market_light新鲜VIX,弃滞后8h parquet) + 同行单日盲判(market_light顺带拉IONQ/RGTI,追赶信号从缓存滞后盲判→每日可判) [done]
2026-07-15 [fable] AI自检07-15三连查: 价格段-7.12% vs 量能段-4.6%双口径 / CPI m/m预测-0.1%抓取可疑 / IONQ新闻误挂QBTS ticker(news.py主体重标) · CPI -0.1%销案(FF无误,实际-0.4%已验证): backend/dashboard/intraday.py, backend/dashboard/news.py [done]
2026-07-15 [fable] QBTZ/QBTX持有军规状态化: 回测判死(QBTZ状态出场−99%最差/空腿全灭),军规不动零部署 → mining.md 第二十三轮; 顺带修07-14 CPI前值当实际bug(decision.py宏观段未回填标注) [done]
2026-07-15 [fable] 观察组第5号卡(用户拍板): 锁翻多×QBTX×3天 → replay.py obs_lockflip(纯后端,factors页数据驱动免改); 补注:82%胜率对执行口径脆弱(收盘定仓5/11),总收益两口径>+500% [done]
2026-07-16 [fable] AI自检07-16: PPI '已公布1.1%'=FRED未更新期错位污染(上月值冒充实际,值容差被巧合击穿) → fred.py 全系列参考期硬校验 _ref_ok + core ppi 显式不支持 [done]
2026-07-16 [fable] /dca 页 VTI/VEA/VWO/BND 价格全空: 盘前 yfinance 当日占位bar close=NaN 静默传染四字段(error=None) → dca.py dropna 修复,价格退回昨收 [done]
2026-07-16 [fable] AI自检扩展全站(用户拍板): selfcheck.py 规则层(六页,历史事故化检查)+Haiku语义层 → publish §4.8 + lambda 同步接线,site_check 回写 snapshot;前端 getSiteCheck 轻量切片 + SelfCheckCard 六页嵌入 + 主页汇总卡 + v2.17.0;真数据验证抓到 PPI/dca 两个已知bug [done]
2026-07-16 [fable] 体检首日调校: Haiku 4/4误报(口径不懂) → prompt 加字段语义表+正反例; 跨页同票价格检查下沉规则层(_check_cross,毒测实证LLM抓不稳) [done]
2026-07-16 [fable] EDGAR 监控扩展 8-K 重大事件(用户拍板): altdata.fetch_sec_events(item解码/严重度分级) + snapshot extras + decision prompt 渲染;实测抓到 07-14 换所 8-K(3.01) [done]
2026-07-17 [fable] 自选账本 v1 学费归档展示(用户要求删v1,改为折叠归档保数据): watch/page.tsx PaperPanel 头部四格只算v2 + v1 details折叠 + data.ts epoch 字段 + v2.17.1 [done]
2026-07-17 [fable] 自读 AI 自检修当日 bug: ①edge命中21%→prompt Wilson上界<50%动态反向警告 ②Philly Fed回填映射(41.4实测)/Core Retail显式不支持 ③特调buy_trigger_px反解%R(实测$18.80) ④挑战digest字段名sleeve_cash/floor_line [done]
2026-07-17 [fable] 元模型 edge v2 重设计(用户下令): 单源帽±0.35+软信号帽±0.50+实测regime门(锁±0.14/QQQ50 +0.13/−0.29)+死区42-58%+model:v2分代记账 → mining.md 第二十四轮 [done]
2026-07-17 [fable] 轮动图加商品点+象限速览条(用户拍板): sector_rotation.py +GLD/USO(商品vs股市相对强度) + rotation-map.tsx 象限分组文字条(17点挤图找不到能源金矿的保底) + v2.18.0 [done]
