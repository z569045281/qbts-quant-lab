"""🔬 第二考场 —— 第二只票的「涨/跌表态」测量轨(2026-07-30 用户点单)。

## 为什么存在

REVIEW-2026-07 §5 的算术:判决主体(方向表态)每个交易日只 +1 个样本,
9 月初才够 n=30 出第一次真判决 —— 而**一个考场的结论永远可能是运气**。
加第二只**低相关**的票,样本速度翻倍,且变成两场独立考试:两边都显不出本事,
那就是真没本事;只有一边行,那大概是噪声。

## 为什么是 MU(2026-07-30 实测选出)

  · 与 QBTS 日收益相关仅 **+0.28**(整年)/ **+0.35**(近 60 日)—— 真独立。
    IONQ **0.81** / RGTI **0.88** / OKLO 0.65 / ASTS 0.55 是同一个赌注下两遍,已排除。
  · 2× 工具 **MUU 日均成交 $2.7B** —— 所有候选里最厚(QBTX/QBTZ 薄得多)。
  · **有真财报**(营收 $90B / 净利 $50B / PE 18)→ 财报日历、宏观日历、板块轮动、
    以及 edge 里实测最强的「QQQ vs 50 日线」(线上 52.5% / 线下 41.9%)在 MU 身上
    **才开始有意义**;这些模块装在营收为 0、对宏观免疫的 QBTS 上一直是摆设(第十五轮)。
  · 已在 scan.py 的 watchlist 里 → 数据管道现成。

## ⚠️ 选票理由里被自己推翻的一条(2026-07-30 当天实测,别装看不见)

首版选 MU 的理由之一是"跳空少 → 系统盲区小"。**按近 60 日窗口这条是错的**:

    窗口        年化波动   跳空≥8%   3日中位波幅   与QBTS相关
    MU  整年       77%      2.2%       5.5%        +0.28
    MU  近60日    114%      6.7%       9.0%        +0.35   ← 变了个动物
    QBTS 近60日   124%      3.3%       6.8%           —
    NVDA 近60日    42%      0.0%       2.4%        +0.18

**MU 当下比 QBTS 还猛,跳空 ≥8% 的频率是它的两倍。** 也就是第二十八轮那个
"技术面在该档无分辨力(p=0.72)"的盲区,在 MU 身上**比 QBTS 更严重**,不是更轻。

保留 MU 的理由只剩(仍然充分):**低相关 + 有真财报 + 工具厚**。放弃的理由不成立
—— 因为本轨是**测量**不是交易,波动大只影响每笔盈亏,不影响能不能测方向。

若要一个零盲区的考场:**NVDA**(跳空 0.0%、相关 +0.18 更低)。本模块所有函数都
带 `ticker` 参数、`_TICKERS` 是个列表,加 NVDA 是**一行配置**,不用改逻辑。

## 六条纪律(改这个文件前先读)

1. **只表态,不给动作。** 没有 entry/stop/target、没有仓位建议、没有 ntfy 推送。
   表态可以说 down —— 因为**没有任何东西会去执行它**。QBTS 空腿是"动作判死",
   这里连动作都不存在,所以不构成复活;**也绝不能拿"换了票没测过"当开空的后门。**
2. **绝不写 decision_journal。** 自己一张表 `second_journal`,记录 id 带 ticker 前缀。
   混进 QBTS 的池子 = 污染预注册样本。
3. **零决策权于 QBTS。** MU 的表态不进 QBTS 的 snapshot/prompt/edge —— 否则两个
   考场互相看答案,独立性就没了。
4. **同一个考场标准**:同一个模型(`decision._MODEL` + 同一个 fallback)、同一个
   `bold_call` 语义、同一套多视界评分(直接复用 `journal._horizon_grades`)、
   同一条预注册判决线(`audit._HORIZON_RULE`)。换标准 = 换考试,不算第二场。
5. **判决分池**。MU 池与 QBTS 池分开报、分开判,不合并成一个大 n
   (两只票同一天的表态不独立 —— 都受大盘影响 —— 合并会虚增有效样本)。
6. **成本可见**:每天 1 次 LLM 调用。不重试、不影子、不并发。
7. **一个信息集只准问一次**(2026-09-02 加)。幂等键 = `<票>-<as_of>`,**不是日历日**。
   周末跑、盘前跑拿到昨天的 bar —— 这两种情况的 as_of 都撞已有记录,直接跳过。

## ⚠️ 2026-09-02 修的三个记账 bug(用户问「能用了吗」查出来的)

上线一个月攒了 25 条记录,**其中只有 18 个独立信息集**(28% 是同一道题问两遍):

    date        wd   as_of        price     ← 重复来源
    2026-08-09  Sun  2026-08-07   877.57    周末也记账(没有交易日闸门)
    2026-08-10  Mon  2026-08-07   877.57
    2026-08-16  Sun  2026-08-14   971.66    ← 周日
    2026-08-17  Mon  2026-08-14   971.66
    2026-08-06  Thu  2026-08-05   893.19    盘前跑,yfinance 还没出当天 bar
    (08-23/08-25/08-27/08-30/08-31 同理)

1. **周末也记账** —— `record()` 用 ET 日历日,没有交易日闸门。4 个周日各一条。
2. **幂等键用日历日** —— 同一个 as_of 能长出两条,纪律 5「不许虚增样本」被架空。
3. **评分锚点用 `date` 而不是 `as_of`** —— 价格属于 as_of(常常是 date−1),窗口却从
   date 之后起算 → 「1d 收益」有时 1 根 bar、有时 2 根,**视界长度随当天几点跑而变**。
   不是未来函数(评分 bar 始终晚于 as_of),但视界标签是错的,而判决线第四条
   正要求「非四视界中的孤例」—— 标签不干净,那条根本没法判。

1+2 一个修就够:**键改成 as_of**,重复自动撞键跳过,周末闸门都不用单独写。
3 是 `grade()` 里一行。25 条已按 as_of 合并成 18 条(重复组保留**最早问的那条** ——
留后一条等于挑答案),horizons 已全部按新锚点重算。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

# 第二考场在册的票。**加票是一行配置**(每加一只 = 每天多 1 次 LLM 调用,约 $0.1)。
# 顺序即展示顺序;TICKER 是默认/单票接口的那只。
_TICKERS = ["MU"]
TICKER = _TICKERS[0]
_TABLE = "second_journal"

# 与 QBTS 表态逐字同义(纪律 4):强制二选一,没有中间选项。
# ⚠️ 结构化输出的 schema **不支持** number/integer 的 minimum/maximum,也不支持
# string 的 maxLength(API 直接 400,首版栽过)——照 decision.py `_DECISION_SCHEMA`
# 的写法:只声明类型,范围在解析后用代码 clamp。
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["p_up_5d", "bold_call_5d", "conviction", "why"],
    "properties": {
        "p_up_5d":      {"type": "number"},
        "bold_call_5d": {"type": "string", "enum": ["up", "down"]},
        "conviction":   {"type": "integer"},
        "why":          {"type": "string"},
    },
}

_SYSTEM = (
    "你是一名纪律严明的量化交易员,只做一件事:对给定股票未来 5 个交易日的方向"
    "给出一个**强制二选一**的表态,并给出你对上涨的真实概率判断。\n"
    "硬规则:\n"
    "1. `bold_call_5d` 必须是 up 或 down,**不许骑墙**。即使证据五五开也要押一边。\n"
    "2. `p_up_5d` 是你的真实概率判断,不是仓位建议。若你确实没把握就写接近 0.50 —— "
    "   但表态仍须二选一。**不要为了让表态好看而扭曲这个概率。**\n"
    "3. 这是**纯测量**:没有人会照你的表态下单,不要考虑仓位、止损或风险管理。\n"
    "4. `why` 一句话(≤120 字)讲你押这边的**主因**,不要复述所有读数。\n"
    "5. 若简报里出现『技术面熔断』提示(跳空 ≥8%),据实降低 conviction 并在 why 里说明 —— "
    "   实测该档技术面无分辨力。"
)


from dashboard.db import supabase as _supabase   # 全仓共用一个客户端


def _load() -> list[dict]:
    sb = _supabase()
    if sb is None:
        return []
    try:
        rows = sb.table(_TABLE).select("data").execute().data
        return [r["data"] for r in rows if r.get("data")]
    except Exception as e:
        logger.warning(f"second_ticker: load failed — {e}")
        return []


def _save(records: list[dict]) -> bool:
    """写库。**返回是否真的写成功** —— 不许静默失败:表还没建时若返回成功,
    页面会显示一个根本没落库的表态,第二天凭空消失,台账等于假账。"""
    sb = _supabase()
    if sb is None or not records:
        return False
    try:
        sb.table(_TABLE).upsert([{"id": r["id"], "data": r} for r in records]).execute()
        return True
    except Exception as e:
        logger.warning(f"second_ticker: save failed — {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  简报:全部复用已有的通用模块(它们都只吃 DataFrame,本来就与票无关)
# ─────────────────────────────────────────────────────────────────────────────
def _drop_incomplete_bar(d: pd.DataFrame) -> pd.DataFrame:
    """丢掉「今天还没收盘」的那根 bar,保证 as_of 指向一根**已完成**的交易日。

    2026-09-02 实测的第四个 bug:job 09:00 ET 跑,yfinance 会给出一根日期为今天的
    占位 bar,close 有时是昨天的值 —— 于是 `as_of` 写着今天,`price` 其实是昨天的:

        as_of=2026-08-17 记的 $971.66 · 该日真实收盘 $1011.75(差 4%,记的是 08-14 的)
        as_of=2026-08-26 记的 $938.48 · 真实 $938.40   (盘中快照)
        as_of=2026-08-28 记的 $933.30 · 真实 $932.86   (盘中快照)

    18 条里 3 条对不上。**as_of 是评分锚点**,它指错了日子,整条记录的视界就错位。
    这与 dca.py 2026-07-16 那个「盘前占位 bar close=NaN 静默传染」是同一个家族
    (见 docs/LESSONS.md),那次是 NaN 好歹能 dropna 掉,这次是**陈旧的真值**,
    dropna 抓不住 —— 只能靠时钟判断。
    """
    if d is None or d.empty:
        return d
    now = datetime.now(ZoneInfo("America/New_York"))
    try:
        last = pd.Timestamp(d.index[-1]).date()
    except Exception:
        return d
    # 收盘 16:00 ET;留 5 分钟给数据落地,与 tiaojiu 的 16:05 心跳同一个数。
    closed = now.hour > 16 or (now.hour == 16 and now.minute >= 5)
    if last == now.date() and not closed and len(d) > 2:
        logger.info("second_ticker: 丢掉未收盘的 %s bar,as_of 退回 %s",
                    last, pd.Timestamp(d.index[-2]).date())
        return d.iloc[:-1]
    return d



def build_brief(ticker: str = TICKER) -> dict:
    """组装该票的证据简报。**不新写任何指标** —— 复用现役模块,
    这样第二考场考的是同一套东西,不是一套新东西。"""
    from data.fetcher import load_or_fetch
    from dashboard.smc import analyze_smc
    from dashboard.regime import analyze_regime
    from dashboard.nadaraya_watson import analyze_nw_envelope
    from dashboard.wavetrend import analyze_wavetrend
    from dashboard.volume_profile import analyze_volume_profile
    from dashboard.event_day import detect_event_day

    df_h, df_d = load_or_fetch(ticker)
    d = df_d.rename(columns=str.lower)
    d = _drop_incomplete_bar(d)
    close = float(d["close"].iloc[-1])
    prev = float(d["close"].iloc[-2])
    brief: dict = {
        "ticker": ticker,
        "as_of": str(d.index[-1])[:10],
        "price": round(close, 2),
        "today_change_pct": round((close / prev - 1) * 100, 2),
        "ohlc10": [
            {"d": str(i)[:10], "o": round(float(r.open), 2), "h": round(float(r.high), 2),
             "l": round(float(r.low), 2), "c": round(float(r.close), 2)}
            for i, r in d.tail(10).iterrows()
        ],
    }
    for name, fn in (
        ("smc",     lambda: analyze_smc(d, df_h=df_h.rename(columns=str.lower) if df_h is not None else None)),
        ("regime",  lambda: analyze_regime(d)),
        ("nw",      lambda: analyze_nw_envelope(d)),
        ("wt",      lambda: analyze_wavetrend(d)),
        ("poc",     lambda: analyze_volume_profile(df_h.rename(columns=str.lower)) if df_h is not None else None),
    ):
        try:
            brief[name] = fn()
        except Exception as e:                    # 单个模块坏掉不许拖垮整轨
            logger.warning(f"second_ticker[{ticker}]: {name} failed — {e}")
            brief[name] = None
    # 事件日熔断(第二十八轮):跳空 ≥8% 档技术面实测无分辨力 → 必须在简报里明示。
    # ⚠️ 口径说明:该熔断的实测依据来自 **QBTS** 的样本。MU 跳空 ≥8% 的频率恰好也是
    # 2.2%(2026-07-30 实测),但"技术面在该档失效"这条**没有在 MU 上单独验证过**。
    # 这里仍然挂上,是因为方向是保守的(让模型少说话),不是因为已被证明。
    try:
        brief["event_day"] = detect_event_day(d, live_price=None, catalyst=None)
    except Exception as e:
        logger.warning(f"second_ticker[{ticker}]: event_day failed — {e}")
        brief["event_day"] = None
    # 大盘机制:edge 里实测最强的单项(线下 41.9% / 线上 52.5%)。QBTS 对宏观免疫
    # 所以它在那边是摆设,在 MU 这种跟随半导体/大盘的票上才有意义。
    try:
        import yfinance as yf
        # ⚠️ yf.download 单票也返回 DataFrame(列是 MultiIndex)→ 必须 squeeze 成 Series,
        # 否则 float() 拿到的是 Series 直接抛 TypeError(首版就栽在这)。
        qqq = yf.download("QQQ", period="6mo", progress=False,
                          auto_adjust=True)["Close"].dropna().squeeze()
        ma50 = float(qqq.rolling(50).mean().iloc[-1])
        last = float(qqq.iloc[-1])
        brief["market"] = {"qqq": round(last, 2), "ma50": round(ma50, 2),
                           "vs_ma50_pct": round((last / ma50 - 1) * 100, 2)}
    except Exception as e:
        logger.warning(f"second_ticker[{ticker}]: market light failed — {e}")
        brief["market"] = None
    # 该票在 scan 里已经算好的基本面/财报/增发(每天扫描已产出,这里只借用)
    try:
        from dashboard.scan import scan_ticker
        card, _ = scan_ticker(ticker)
        # 键名照 scan_ticker 的真实契约取(首版猜了 verdict/note,两个都不存在 → 打印出 None)
        brief["scan"] = {k: card.get(k) for k in
                         ("score", "stance", "trend", "notes", "levels", "rsi", "vol_annual",
                          "earnings", "dilution", "fundamentals", "theme", "trigger")}
    except Exception as e:
        logger.warning(f"second_ticker[{ticker}]: scan failed — {e}")
        brief["scan"] = None
    return brief


def _fmt_brief(b: dict) -> str:
    """简报 → 中文文本。刻意**不**做成 QBTS 那 30 段的规模:那 30 段里很多是
    QBTS 专属(量子板块、姐妹票、SEC 8-K),硬搬过来是假的丰富。这里只放
    确实通用、且在 MU 身上有意义的读数。"""
    L = [f"# {b['ticker']} 证据简报(数据截至 {b['as_of']})",
         f"收盘 ${b['price']},当日 {b['today_change_pct']:+.2f}%"]
    ev = b.get("event_day")
    if ev:
        from dashboard.event_day import prompt_block
        # 复用现役 prompt 段(纪律 4:不写第二套措辞),但去掉 QBTS 专属的第 ④ 条
        # ——那条讲的是"不得因涨太多建议做空 QBTS",这里连动作都没有。
        blk = prompt_block(ev)
        L.append("\n" + blk.split("④")[0].rstrip())
        L.append("  (本轨只出表态,原规则第 ④ 条关于做空动作的部分不适用)")
    L.append("\n## 最近 10 日 OHLC")
    for r in b["ohlc10"]:
        L.append(f"  {r['d']}  O{r['o']} H{r['h']} L{r['l']} C{r['c']}")
    smc = b.get("smc") or {}
    if smc:
        le = smc.get("last_event") or {}
        rp = smc.get("range_position")
        L.append(f"\n## SMC 结构")
        L.append(f"  日线趋势【{smc.get('trend', '?')}】")
        if le:
            L.append(f"  最近结构事件 {le.get('kind', '—')} @ ${le.get('level', '—')}"
                     f"({le.get('date', '—')})")
        if rp is not None:
            L.append(f"  区间位置 {rp * 100:.0f}%(0=区间底 / 100=区间顶)")
        L.append(f"  机械信号 {smc.get('signal', '—')} · {smc.get('rationale', '')}")
    reg = b.get("regime") or {}
    if reg:
        L.append(f"\n## 波动率 Regime\n  {reg.get('rationale', '—')}")
    nw = b.get("nw") or {}
    if nw:
        L.append(f"\n## Nadaraya-Watson 包络(非重绘)\n  {nw.get('rationale', '—')}")
    wt = b.get("wt") or {}
    if wt:
        L.append(f"\n## WaveTrend(日线)\n  wt1={wt.get('wt1')} wt2={wt.get('wt2')} "
                 f"状态 {wt.get('state', '—')}")
    poc = b.get("poc") or {}
    if poc:
        L.append(f"\n## 成交量画像 / POC\n  {poc.get('note', '—')}")
    mk = b.get("market") or {}
    if mk:
        L.append(f"\n## 大盘机制(本系统实测最强单项)\n  QQQ ${mk['qqq']} vs 50日线 "
                 f"${mk['ma50']} = {mk['vs_ma50_pct']:+.2f}%"
                 f"\n  实测:QQQ 在 50 日线上方时 P(5日涨)=52.5%,下方 41.9%。")
    sc = b.get("scan") or {}
    if sc:
        L.append(f"\n## 机械扫描(scan.py 同一套打分)")
        L.append(f"  评分 {sc.get('score')} · 立场【{sc.get('stance', '—')}】"
                 f" · 趋势 {sc.get('trend', '—')} · RSI {sc.get('rsi', '—')}"
                 f" · 年化波动 {sc.get('vol_annual', '—')}")
        for n in (sc.get("notes") or [])[:5]:
            L.append(f"  · {n}")
        ea = sc.get("earnings") or {}
        if ea.get("date"):
            L.append(f"  财报: {ea['date']}(还有 {ea.get('days', '?')} 天)")
        di = sc.get("dilution") or {}
        if di.get("label"):
            L.append(f"  SEC 增发/稀释: {di['label']}")
        fu = sc.get("fundamentals") or {}
        if fu:
            L.append(f"  基本面: {fu}")
    L.append("\n---\n只回答方向表态。没有人会照它下单。")
    return "\n".join(L)


def generate_lean(ticker: str = TICKER, brief: dict | None = None) -> dict:
    """一次 LLM 调用 → {p_up_5d, bold_call_5d, conviction, why}。
    模型与 fallback 直接借 decision.py 的常量(纪律 4:同一个考场标准)。"""
    import anthropic
    from dashboard.decision import _CLIENT, _MODEL, _FALLBACK_MODEL

    b = brief or build_brief(ticker)
    msg = _fmt_brief(b)

    def _call(model: str) -> str:
        resp = _CLIENT.messages.create(
            model=model, max_tokens=8000,
            thinking={"type": "adaptive"},
            system=_SYSTEM,
            messages=[{"role": "user", "content": msg}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        text = next((x.text for x in resp.content if getattr(x, "type", "") == "text"), "").strip()
        if not text:
            raise ValueError(f"no text block (stop_reason={resp.stop_reason})")
        return text

    try:
        text, used = _call(_MODEL), _MODEL
    except (anthropic.APIError, ValueError) as e:
        logger.warning("second_ticker: %s failed (%s) → %s", _MODEL, str(e)[:160], _FALLBACK_MODEL)
        text, used = _call(_FALLBACK_MODEL), _FALLBACK_MODEL
    lean = json.loads(text)
    lean["model"] = used
    lean["p_up_5d"] = max(0.0, min(1.0, float(lean["p_up_5d"])))
    lean["conviction"] = max(0, min(10, int(lean["conviction"])))
    if lean["bold_call_5d"] not in ("up", "down"):
        raise ValueError(f"bad bold_call: {lean['bold_call_5d']}")
    return lean


def record(ticker: str = TICKER, lean: dict | None = None, brief: dict | None = None) -> dict | None:
    """记一条表态。**幂等键 = `<票>-<as_of>`,一个信息集只准问一次。**
    返回该条记录;已问过 / 拿不到 Supabase / LLM 失败 → None(测量轨不许拖垮主链路)。

    ⚠️ 2026-09-02 修:键原本是 `<票>-<今天的日历日>`,导致 25 条记录里只有 18 个
    独立信息集(28% 是重复问)。两个来源:
      · **周末也记账** —— 没有交易日闸门,4 个周日各记一条,全用周五的数据。
      · **盘前跑拿到昨天的 bar** —— job 09:00 ET 跑,yfinance 常常还没出当天 bar,
        于是今天和昨天的记录 as_of 相同(08-06/08-17/08-25/08-27 都是)。
    改键之后两种情况自动合并成一条,周末闸门都不用单独写 —— 周日跑出来的 as_of
    就是周五,撞上周五那条,直接跳过。**这是纪律 5「不许虚增样本」的落地。**

    **同一个 as_of 已有记录 → 跳过,不重问也不覆盖。** 覆盖 = 对同一道题重摇一次
    骰子再留后一个答案,那是在挑答案,不是在测量。
    """
    if _supabase() is None:
        logger.warning("second_ticker: no Supabase — 测量轨跳过(本地文件回退会造成假账本)")
        return None
    try:
        b = brief or build_brief(ticker)
    except Exception as e:
        logger.warning(f"second_ticker[{ticker}]: brief failed — {e}")
        return None
    rid = f"{ticker}-{b['as_of']}"
    # 查重放在 LLM 调用**之前** —— 既省掉那次调用($0.1/次,纪律 6 成本可见),
    # 也保证已落库的表态不会被同一道题的第二次回答改写。
    if any(r.get("id") == rid for r in _load()):
        logger.info("second_ticker[%s]: as_of %s 已有表态,跳过(一个信息集只问一次)",
                    ticker, b["as_of"])
        return None
    try:
        ln = lean or generate_lean(ticker, b)
    except Exception as e:
        logger.warning(f"second_ticker[{ticker}]: lean failed — {e}")
        return None
    # 范围 clamp **在这里也做一遍**:结构化输出的 schema 无法约束 minimum/maximum
    # (API 直接 400),所以代码是唯一防线;`lean` 又可由调用方传入绕过 generate_lean。
    # 落库点必须自己保证不变量 —— 台账里出现 p_up=1.4 就再也算不对基线了。
    if ln["bold_call_5d"] not in ("up", "down"):
        logger.warning(f"second_ticker[{ticker}]: 非法表态 {ln['bold_call_5d']!r},丢弃")
        return None
    rec = {
        # date = 这条表态是哪天问的(审计用);as_of = 价格/证据属于哪根 bar(评分锚点)。
        # 两者常常差一天,**评分必须用 as_of**(见 grade())。
        "id": rid, "ticker": ticker,
        "date": datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d"),
        "as_of": b["as_of"],
        "price": b["price"],
        "p_up_5d": round(max(0.0, min(1.0, float(ln["p_up_5d"]))), 3),
        "bold_call_5d": ln["bold_call_5d"],
        "conviction": max(0, min(10, int(ln["conviction"]))),
        "why": (ln.get("why") or "")[:300],
        "model": ln.get("model"),
        "technical_muted": bool((b.get("event_day") or {}).get("technical_muted")),
        "status": "pending", "horizons": None,
    }
    # upsert by id → 同日重跑覆盖当日那条,不会长出第二条(幂等)
    if not _save([rec]):
        logger.warning("second_ticker[%s]: 表态已生成但**没落库**(表是否已建?"
                       "跑 sql/second_journal_migration.sql)—— 按未记录处理", ticker)
        return None
    logger.info("second_ticker[%s] %s → %s (p_up %.2f, conv %d)",
                ticker, today, rec["bold_call_5d"], rec["p_up_5d"], rec["conviction"])
    return rec


def grade(ticker: str = TICKER, df_d: pd.DataFrame | None = None) -> int:
    """多视界评分。**直接复用 journal._horizon_grades**(纪律 4)——
    同一段代码算 QBTS 与 MU,口径不可能漂移。幂等,只增不改。"""
    from dashboard.journal import _horizon_grades, _HORIZONS
    from data.fetcher import load_or_fetch

    if df_d is None:
        _, df_d = load_or_fetch(ticker)
    d = df_d.rename(columns=str.lower)
    closes = d["close"]
    dates = pd.DatetimeIndex(d.index).normalize()
    records = [r for r in _load() if r.get("ticker") == ticker]
    touched = []
    for r in records:
        try:
            # ⚠️ 2026-09-02 修:锚点必须是 **as_of**(价格所属的那根 bar),不是 `date`
            # (表态被问出来的日历日)。原来用 date:价格属于 as_of=date−1,而窗口从
            # date 之后起算 → 「1d 收益」有时真是 1 根 bar、有时是 2 根,**视界长度
            # 随当天几点跑而变**。不是未来函数(评分 bar 始终晚于 as_of),但视界标签
            # 是错的,四个视界横向比就不干净 —— 而判决线第四条正要求「非四视界中的孤例」。
            d0 = pd.Timestamp(r.get("as_of") or r["date"]).normalize()
            p0 = float(r["price"])
        except (KeyError, TypeError, ValueError):
            continue
        after = dates[dates > d0]
        fwd, bold = _horizon_grades(r, p0, closes, after)
        if not fwd:
            continue
        blk = {"fwd_ret": fwd, "bold": bold}
        if r.get("horizons") == blk:
            continue
        r["horizons"] = blk
        # 最长视界到期 → 结案(与 QBTS 的 5 日闸门同一个数)
        r["status"] = "graded" if f"{max(_HORIZONS)}d" in fwd else "pending"
        touched.append(r)
    if touched:
        _save(touched)
    return len(touched)


def run_daily() -> dict:
    """每日一次:先评分(补齐历史视界)再记今天的表态。发布链路调这个。

    **顺序重要**:先 grade 再 record —— 否则今天刚写的 pending 记录会被立刻
    "评分"一遍(它还没有任何 after bar,`_horizon_grades` 返回空,白跑一趟)。
    单票失败不影响其它票(测量轨不许拖垮主链路)。
    """
    out: dict = {"graded": {}, "recorded": {}}
    for t in _TICKERS:
        try:
            out["graded"][t] = grade(t)
        except Exception as e:
            logger.warning(f"second_ticker[{t}]: grade failed — {e}")
            out["graded"][t] = None
        try:
            rec = record(t)
            # 2026-09-02:跳过(周末 / 盘前还没出新 bar → as_of 已问过)是**正常**路径,
            # 不是失败。原来两者都记 None,CloudWatch 里分不出"今天本来就不该记"和
            # "今天该记但炸了"—— 而这条日志是唯一的监控。
            out["recorded"][t] = rec["bold_call_5d"] if rec else "skipped_or_failed"
        except Exception as e:
            logger.warning(f"second_ticker[{t}]: record failed — {e}")
            out["recorded"][t] = None
    return out


def load_all_boards(n: int = 30) -> dict | None:
    """/mu 页面的 payload:在册每只票一块。全空则返回 None(页面显示未开始)。"""
    boards = {}
    for t in _TICKERS:
        try:
            b = load_board(t, n)
        except Exception as e:
            logger.warning(f"second_ticker[{t}]: board failed — {e}")
            b = None
        if b:
            boards[t] = b
    if not boards:
        return None
    return {"tickers": _TICKERS, "boards": boards}


def load_board(ticker: str = TICKER, n: int = 30) -> dict | None:
    """给 /mu 页面的 payload:最近表态 + 逐视界成绩 + 明确的纪律声明。"""
    from dashboard.audit import _HORIZON_RULE, _verdict
    from dashboard.journal import _HORIZONS

    # 按 as_of 排 —— 它才是样本身份(2026-09-02 起 id 也是它)。`date` 只是被问的日历日。
    recs = sorted([r for r in _load() if r.get("ticker") == ticker],
                  key=lambda r: r.get("as_of") or r.get("date", ""), reverse=True)
    if not recs:
        return None
    by_h = {}
    for h in _HORIZONS:
        key = f"{h}d"
        rows = [(r.get("bold_call_5d"), (r.get("horizons") or {}).get("fwd_ret", {}).get(key))
                for r in recs]
        rows = [(c, f) for c, f in rows if c in ("up", "down") and f is not None]
        allf = [f for r in recs
                for f in [(r.get("horizons") or {}).get("fwd_ret", {}).get(key)] if f is not None]
        if not rows or not allf:
            continue
        down_share = sum(1 for f in allf if f < 0) / len(allf)
        base = max(down_share, 1 - down_share)
        hits = sum(1 for c, f in rows if (c == "up") == (f > 0))
        v = _verdict(hits, len(rows), breakeven=base)
        v.update(baseline=round(base, 3),
                 baseline_side="down" if down_share >= 0.5 else "up",
                 skill_pp=round((hits / len(rows) - base) * 100, 1))
        by_h[key] = v
    latest = recs[0]
    return {
        "ticker": ticker,
        "why_this_ticker": ("与 QBTS 日收益相关仅 +0.28(整年)/+0.35(近60日)—— 真独立。"
                            "IONQ 0.81、RGTI 0.88 是同一个赌注下两遍,已排除。"
                            "2× 工具 MUU 日均 $2.7B(最厚)。有真财报($90B 营收/$50B 净利)"
                            "→ 财报、宏观、板块、以及实测最强的「QQQ vs 50日线」在它身上才有意义;"
                            "这些模块装在营收为 0、对宏观免疫的 QBTS 上一直是摆设。"),
        "known_weakness": ("选它的理由里有一条被当天实测推翻了:我原说「跳空少所以盲区小」,"
                           "但按近 60 日窗口 MU 跳空 ≥8% 的频率是 6.7%,**是 QBTS(3.3%)的两倍**,"
                           "年化波动也从 77% 跳到 114%。第二十八轮那个「技术面在该档无分辨力"
                           "(p=0.72)」的盲区,在 MU 身上比 QBTS 更严重。保留它的理由只剩"
                           "低相关 + 真财报 + 工具厚 —— 对「测方向」这件事仍然充分,"
                           "因为波动大只影响每笔盈亏,不影响能不能测。"),
        "latest": latest,
        "records": recs[:n],
        "n_total": len(recs),
        "by_horizon": by_h,
        "rule": _HORIZON_RULE,
        "discipline_cn": ("纯测量轨:只出方向表态,不给入场/止损/目标、不给仓位建议、不发推送。"
                          "表态可以说 down,因为没有任何东西会去执行它 —— 这不是复活做空腿。"
                          "与 QBTS 台账分池存放、分池判决(同一天两只票的表态不独立,合并会虚增样本)。"),
    }


if __name__ == "__main__":
    # 只自测 2026-09-02 新加的那道闸(其余路径都要 Supabase / LLM,不适合无网自测)。
    logging.basicConfig(level=logging.INFO)
    _now = datetime.now(ZoneInfo("America/New_York"))
    _closed = _now.hour > 16 or (_now.hour == 16 and _now.minute >= 5)
    _mk = lambda ds: pd.DataFrame({"close": range(len(ds))}, index=pd.to_datetime(ds))

    _today = _now.date().isoformat()
    assert len(_drop_incomplete_bar(_mk(["2026-01-02", "2026-01-05", _today]))) == (3 if _closed else 2)
    assert len(_drop_incomplete_bar(_mk(["2026-01-02", "2026-01-05", "2026-01-06"]))) == 3   # 过去的日子原样
    assert len(_drop_incomplete_bar(_mk(["2026-01-05", _today]))) == 2                       # 只剩2根不丢
    assert _drop_incomplete_bar(pd.DataFrame()).empty and _drop_incomplete_bar(None) is None
    print(f"✅ _drop_incomplete_bar 自测通过(ET {_now:%H:%M},{'已' if _closed else '未'}收盘)")
