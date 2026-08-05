"""🚨 财报落地即时推送 —— 数字一出来就响,不等决策卡。

**出身(2026-08-05,用户点单)**:「我需要在财报出来的第一时间收到 ntfy 提醒」。
QBTS 财报是**盘前 08:00 ET** 发(= 墨尔本晚上 22:00,用户醒着),而每日决策卡
09:00 ET 才跑 —— 中间那一个小时正是价格跳最凶的时候,却没有任何通知。

━━ 三个探针,任一命中就推(报出是哪个命中的)━━━━━━━━━━━━━━━━━

① **EDGAR 8-K item 2.02**(Results of Operations)—— 唯一权威来源。公司发新闻稿的
   同时(或几分钟内)报这份表。**它是"财报确实发了"的事实,不是推测。**
② **盘前价格跳动 ≥5%** —— 数字出来了、市场已经反应。比 ①快,但可能被别的消息触发,
   所以推送里写清楚"由价格触发,未见 8-K",不冒充已确认。
③ **新闻标题命中财报关键词** —— 吃 catalyst_radar 这一跳已经抓好的条目,零额外成本。

**不做的事(刻意)**:不解析 EPS/营收数字。8-K 正文是 HTML 附件,格式每季度都变,
解析失败率高而且错一位比没有更糟。**速度优先:先告诉你"出来了 + 现在什么价",
数字你自己看。** 推送里带上一致预期,方便你一眼对照。

**零决策权**:不给方向、不给动作。财报是二元事件,系统对它没有预测能力
(第三十二轮实测)。这条推送只做"叫醒"这一件事。

⚠️ 状态存 live_quote(整块覆写)—— 非工作跳一律 `return prev`,否则重复响铃
(2026-07-31 事件日那次事故的同一个坑)。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TICKER = "QBTS"
# 盘前 06:00 → 盘后 17:00 ET。QBTS 历来盘前 08:00 发,窗口给宽一点兜住改期/延迟。
_WIN_START = 6 * 60
_WIN_END = 17 * 60
_EDGAR_EVERY = 2          # 每 2 分钟查一次 EDGAR(礼貌 + 够快)
_PRICE_JUMP = 0.05        # 盘前跳动阈值
_KEYWORDS = ("earnings", "quarterly results", "q1 ", "q2 ", "q3 ", "q4 ",
             "financial results", "reports second quarter", "reports first quarter",
             "reports third quarter", "reports fourth quarter", "财报", "业绩")


def _earnings_today(now_et) -> bool:
    """今天是不是财报日。一天只查一次(结果缓存在 carry 状态里)。"""
    try:
        import yfinance as yf
        cal = yf.Ticker(_TICKER).calendar or {}
        ed = cal.get("Earnings Date")
        if isinstance(ed, (list, tuple)):
            ed = ed[0] if ed else None
        return bool(ed) and str(ed)[:10] == now_et.date().isoformat()
    except Exception as e:
        logger.warning("earnings_alert: 财报日期查询失败: %s", e)
        return False


def _find_8k(now_et) -> dict | None:
    """今天有没有 item 2.02 的 8-K。有 → 返回 {acc, items, url}。"""
    try:
        from data.altdata import _sec_cik, _sec_get, _SEC_SUBMISSIONS
        import json as _json
        cik = _sec_cik(_TICKER)
        if cik is None:
            return None
        raw = _sec_get(_SEC_SUBMISSIONS.format(cik=cik))
        if not raw:
            return None
        rec = (_json.loads(raw).get("filings") or {}).get("recent") or {}
        forms = rec.get("form") or []
        dates = rec.get("filingDate") or []
        items = rec.get("items") or [""] * len(forms)
        accs = rec.get("accessionNumber") or [""] * len(forms)
        docs = rec.get("primaryDocument") or [""] * len(forms)
        today = now_et.date().isoformat()
        for f, ds, its, acc, doc in zip(forms, dates, items, accs, docs):
            if f != "8-K" or ds != today or "2.02" not in (its or ""):
                continue
            a = (acc or "").replace("-", "")
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{a}/{doc}"
                   if a and doc else "https://www.sec.gov/cgi-bin/browse-edgar"
                                     f"?action=getcompany&CIK={cik}&type=8-K")
            return {"acc": acc, "items": its, "url": url}
    except Exception as e:
        logger.warning("earnings_alert: EDGAR 查询失败: %s", e)
    return None


def _news_hit(catalyst: dict | None) -> str | None:
    for it in ((catalyst or {}).get("items") or []):
        t = str(it.get("title") or "")
        low = t.lower()
        if any(k in low for k in _KEYWORDS):
            return t[:90]
    return None


def maybe_earnings_alert(prev: dict | None, now_et, quotes: dict | None,
                         catalyst: dict | None = None) -> dict | None:
    """财报日窗口内每分钟判一次;命中即推一条,每个财报日只推一次。

    非财报日 / 非窗口 / 已推过 → **原样返回 prev**(carry-forward)。
    """
    today = now_et.date().isoformat()
    st = dict(prev) if (prev or {}).get("date") == today else {"date": today}

    hm = now_et.hour * 60 + now_et.minute
    if now_et.weekday() >= 5 or not (_WIN_START <= hm <= _WIN_END):
        return prev
    if st.get("pushed"):
        return st                        # 今天已经响过

    # 是不是财报日 —— 一天只问一次 yfinance,答案缓存在状态里
    if "is_er_day" not in st:
        st["is_er_day"] = _earnings_today(now_et)
    if not st["is_er_day"]:
        return st

    q = ((quotes or {}).get("qbts") or {})
    px = q.get("price")
    chg = q.get("change_pct")
    trusted = q.get("prev_close_trusted")

    hits: list[str] = []
    src = None

    f8k = None
    if now_et.minute % _EDGAR_EVERY == 0:
        f8k = _find_8k(now_et)
    if f8k:
        hits.append(f"EDGAR 8-K item {f8k['items']} 已申报（权威来源）")
        src = "8-K"

    # 前收没对上账时不许据此报警(2026-07-31 教训:一个没校验过的基准凭空造警报)
    if chg is not None and trusted is not False and abs(float(chg)) >= _PRICE_JUMP:
        hits.append(f"盘前较前收 {float(chg)*100:+.1f}%（≥±{_PRICE_JUMP*100:.0f}%）")
        src = src or "price"

    nh = _news_hit(catalyst)
    if nh:
        hits.append(f"新闻命中财报关键词：{nh}")
        src = src or "news"

    if not hits:
        return st

    from dashboard.earnings import analyze_earnings
    con = ((analyze_earnings() or {}).get("consensus")) or {}
    lines = [f"QBTS ${px:.2f}" if isinstance(px, (int, float)) else "QBTS —"]
    lines += [f"· {h}" for h in hits]
    if con.get("eps_avg") is not None:
        lines.append(f"\n一致预期 EPS {con['eps_avg']:+.3f}"
                     + (f" · 营收 ${con['rev_avg']/1e6:.2f}M" if con.get("rev_avg") else ""))
    if src != "8-K":
        lines.append("⚠️ 尚未见到 8-K —— 由" + ("价格" if src == "price" else "新闻")
                     + "触发,数字请自行核对。")
    elif f8k:
        lines.append(f"\n{f8k['url']}")
    lines.append("\n系统对财报**没有预测能力**(第三十二轮实测),这条只叫醒不给方向。\n"
                 "→ 历史当日 |涨跌| 中位 6.2% / 均值 11.3%,杠杆 ETF ×2。\n"
                 "→ 做空仍然不做(全部已知路径已判死)。")

    try:
        from dashboard.intraday_smc import _ntfy
        if _ntfy("QBTS 🚨 财报已落地", "\n".join(lines),
                 tags="rotating_light", priority="urgent"):
            st["pushed"] = True
            st["src"] = src
            st["hits"] = hits
    except Exception as e:
        logger.warning("earnings_alert ntfy failed: %s", e)
    return st
