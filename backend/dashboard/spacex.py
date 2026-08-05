"""
🚀 SpaceX (SPCX) 第二仪表盘 — **DeepSeek-only 决策**(2026-07-13,用户要求)。

与 QBTS 主仪表盘完全独立:
  · QBTS 的大脑是 Fable 5(备 Opus 4.8),动作空间是杠杆 ETF QBTX/QBTZ,带量子
    同业信号、SMC playbook 等一整套。SPCX 是一只**普通个股**(直接买卖、无配对
    杠杆 ETF、无量子同业),照搬那台机器既臃肿又不诚实。
  · 所以这里是一个**自包含**模块:自己抓数据、自己写 SPCX 专用 prompt、
    **只调 DeepSeek V4 Pro**(不碰 Anthropic/Fable),写独立 Supabase 表 spacex_state。
    无 DEEPSEEK_API_KEY 或调用失败 → decision=None,仪表盘显示"等云端刷新",
    绝不回退到 Claude(用户明确"不用 fable")。

⚠️ SPCX 是**新 IPO**(2026 上市,6/16 见顶 $225.64,7/10 见底 $145)。CLAUDE.md
   的铁律:新 IPO 的机械位必须叠加事件背景 —— **2026-08-06 首次财报 + 首次锁定期
   解禁**(约 20% 内部人可卖,达 IPO 价条件另 +10%)是压倒性的近期风险,prompt 与
   数据里都强制点名。锁定期日期/比例需定期复核(硬编码 + re-verify 注)。
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import yfinance as yf


def _utc_now() -> str:
    """upsert 时显式刷新 updated_at —— DEFAULT now() 只管 INSERT。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

logger = logging.getLogger(__name__)

TICKER = "SPCX"
_DS_MODEL = "deepseek-v4-pro"
_DS_URL = "https://api.deepseek.com/chat/completions"

_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "spacex_decision.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── 事件日历(硬编码,需定期复核)──────────────────────────────────────────
# 新 IPO 的机械信号对事件全盲 —— 这几条是决策 prompt 的"事件背书",压倒纯技术位。
_CATALYSTS = [
    {"date": "2026-08-06", "event": "首次财报 + 首次锁定期解禁",
     "impact": "high",
     "note": "上市后第一份财报,同日约 20% 内部人锁定期到期可卖(达 IPO 价条件另 +10% 加入),"
             "是近期最大的供给冲击与波动源。日期/比例来自公开报道,需复核。"},
    {"date": "2026-07", "event": "纳入纳斯达克100指数", "impact": "medium",
     "note": "已完成 —— 指数基金被动买盘是结构性顺风,但'纳入即见光死'的历史案例(参考 PLTR)不少。"},
]
_CATALYST_ASOF = "2026-07-13"


def _series(df: pd.DataFrame, col: str) -> pd.Series:
    s = df[col]
    return s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s


def _rsi(close: pd.Series, n: int = 14) -> float | None:
    if len(close) < n + 1:
        return None
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return float(100 - 100 / (1 + rs.iloc[-1])) if pd.notna(rs.iloc[-1]) else None


def _atr(df: pd.DataFrame, n: int = 14) -> float | None:
    if len(df) < n + 1:
        return None
    h, l, c = _series(df, "High"), _series(df, "Low"), _series(df, "Close")
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def fetch_spacex_data() -> dict:
    """SPCX 全套技术读数(纯 yfinance,零 key)。返回给 prompt + 卡片展示两用。"""
    d = yf.download(TICKER, period="max", interval="1d", auto_adjust=True, progress=False)
    if d is None or d.empty:
        raise ValueError("SPCX 日线数据为空")
    close = _series(d, "Close")
    vol = _series(d, "Volume")
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else price

    def _sma(n):
        return float(close.rolling(n).mean().iloc[-1]) if len(close) >= n else None

    sma20, sma50, sma200 = _sma(20), _sma(50), _sma(200)
    ath = float(close.max())
    atl = float(close.min())
    hi_52 = float(close.tail(252).max())
    lo_52 = float(close.tail(252).min())

    def _ret(n):
        return float(price / close.iloc[-n - 1] - 1) if len(close) > n else None

    atr = _atr(d)
    vol20 = float(vol.tail(20).mean()) if len(vol) >= 20 else float(vol.mean())
    vol_today = float(vol.iloc[-1])

    return {
        "ticker": TICKER,
        "price": round(price, 2),
        "prev_close": round(prev, 2),
        "today_change": round(price / prev - 1, 4) if prev else 0.0,
        "sma20": round(sma20, 2) if sma20 else None,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "above_sma20": (price > sma20) if sma20 else None,
        "above_sma50": (price > sma50) if sma50 else None,
        "above_sma200": (price > sma200) if sma200 else None,
        "rsi14": round(_rsi(close), 1) if _rsi(close) is not None else None,
        "atr14": round(atr, 2) if atr else None,
        "atr_pct": round(atr / price, 4) if atr and price else None,
        "ath": round(ath, 2),
        "atl": round(atl, 2),
        "drawdown_from_ath": round(price / ath - 1, 4) if ath else None,
        "high_52w": round(hi_52, 2),
        "low_52w": round(lo_52, 2),
        "ret_5d": round(_ret(5), 4) if _ret(5) is not None else None,
        "ret_20d": round(_ret(20), 4) if _ret(20) is not None else None,
        "vol_vs_20d": round(vol_today / vol20, 2) if vol20 else None,
        "n_bars": int(len(close)),
        # 薄数据守卫:< 60 根 → 均线/RSI 预热失真,新 IPO 尤其如此。标记出来,
        # prompt 会据此让模型别信技术指标、以事件+价格行为为准(CLAUDE.md 铁律)。
        "thin_data": int(len(close)) < 60,
        "as_of": str(close.index[-1].date()),
    }


def fetch_spacex_news(limit: int = 7) -> list[dict]:
    """SpaceX 相关新闻头条(Google News RSS,免费无 key)。只取标题+时间给 DeepSeek 读。"""
    import requests
    url = ("https://news.google.com/rss/search?q=SpaceX+stock+OR+SPCX+when:3d"
           "&hl=en-US&gl=US&ceid=US:en")
    out: list[dict] = []
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for item in list(root.iter("item"))[:limit]:
            title = (item.findtext("title") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            src_el = item.find("{http://purl.org/dc/elements/1.1/}creator") or item.find("source")
            src = (src_el.text if src_el is not None else "") or ""
            if title:
                out.append({"title": title, "published": pub, "source": src.strip()})
    except Exception as e:
        logger.warning(f"spacex news fetch failed: {e}")
    return out


# ── 抢先量三条腿(2026-07-13,用户要求)──────────────────────────────────────
# 新 IPO 日线只有 ~20 根,标准技术指标失真。这三条腿都**不吃日线历史长度**:
#   ① 期权隐含波动:前瞻预测,零历史需求 —— IV/跨式=市场对未来 ATR/幅度的预测
#   ② 盘中时间框:同样 20 个交易日,1h 线有 ~130 根,RSI/ATR/均线全预热完毕、可用
#   ③ 同业波动先验:借太空同业的一年历史估波动,收缩到自己抖动的短样本上
_EVENT_DATE = "2026-08-06"          # 首财报+首解禁,期权在这前后定价事件溢价
_PEERS = {
    "RKLB": {"name": "火箭实验室", "pure": True},
    "ASTS": {"name": "AST太空移动", "pure": True},
    "LUNR": {"name": "直觉机器", "pure": True},
    "PLTR": {"name": "Palantir·纳入对照", "pure": False},
    "ARKX": {"name": "太空主题ETF", "pure": False},
}
_SHRINK_K = 60      # 收缩常数:自己攒到 ~60 根 bar 前,先验(同业)占主导


def _opt_price(row) -> float | None:
    """期权成交价:盘中用买卖中值,盘后 bid/ask 归零则退回 lastPrice。"""
    bid, ask, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
    if bid and ask and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2
    return float(last) if last and last > 0 else None


def fetch_spacex_options(spot: float) -> dict | None:
    """① 期权隐含波动:ATM 跨式→预期波动%,ATM IV,期限结构,事件到期溢价,IV 偏斜。
    全 best-effort:无期权/数据异常 → None(不阻断)。"""
    try:
        t = yf.Ticker(TICKER)
        exps = list(getattr(t, "options", None) or [])
    except Exception as e:
        logger.warning(f"spacex options list failed: {e}")
        return None
    if not exps:
        return None
    today = datetime.now(timezone.utc).date()
    # 关注 ~70 天内(覆盖 8/6 事件),最多 6 个到期
    chosen = [e for e in exps if e <= "2026-09-30"][:6] or exps[:4]
    term: list[dict] = []
    skew = None
    for exp in chosen:
        try:
            oc = t.option_chain(exp)
            calls, puts = oc.calls, oc.puts
            if calls.empty or puts.empty:
                continue
            calls = calls.assign(_d=(calls["strike"] - spot).abs())
            puts = puts.assign(_d=(puts["strike"] - spot).abs())
            ac = calls.nsmallest(1, "_d").iloc[0]
            ap = puts.nsmallest(1, "_d").iloc[0]
            cp, pp = _opt_price(ac), _opt_price(ap)
            if not cp or not pp:
                continue
            straddle = cp + pp
            ivs = [float(x) for x in (ac.get("impliedVolatility"), ap.get("impliedVolatility"))
                   if isinstance(x, (int, float)) and x > 0]
            atm_iv = sum(ivs) / len(ivs) if ivs else None
            try:
                dte = (date.fromisoformat(exp) - today).days
            except ValueError:
                dte = None
            term.append({
                "expiry": exp, "dte": dte,
                "expected_move_pct": round(straddle / spot, 4) if spot else None,
                "atm_iv": round(atm_iv, 4) if atm_iv else None,
            })
            # 事件到期上算一次 IV 偏斜(~10% OTM 看跌 IV − 看涨 IV;正=下行恐惧买盘)
            if exp >= _EVENT_DATE and skew is None:
                try:
                    otm_p = puts[puts["strike"] <= spot * 0.9]
                    otm_c = calls[calls["strike"] >= spot * 1.1]
                    if not otm_p.empty and not otm_c.empty:
                        pv = float(otm_p.iloc[(otm_p["strike"] - spot * 0.9).abs().argmin()]["impliedVolatility"])
                        cv = float(otm_c.iloc[(otm_c["strike"] - spot * 1.1).abs().argmin()]["impliedVolatility"])
                        if pv > 0 and cv > 0:
                            skew = round(pv - cv, 4)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"spacex opt chain {exp} failed: {e}")
    if not term:
        return None
    event_expiry = next((x for x in term if x["expiry"] >= _EVENT_DATE), None)
    near = term[0]
    return {
        "spot": round(spot, 2),
        "term": term,
        "event_expiry": event_expiry,
        "event_date": _EVENT_DATE,
        "near_expected_move_pct": near.get("expected_move_pct"),
        "skew_put_minus_call": skew,       # 正=看跌 IV 更高=下行恐惧;负=追涨
    }


def fetch_spacex_intraday() -> dict | None:
    """② 盘中时间框(1h):同样 20 个交易日,~130 根 1h bar → RSI/ATR/均线全可用。"""
    try:
        d = yf.download(TICKER, period="1mo", interval="1h",
                        auto_adjust=True, progress=False)
        if d is None or d.empty:
            return None
        close = _series(d, "Close")
        if len(close) < 30:
            return None
        price = float(close.iloc[-1])
        sma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        rsi = _rsi(close)
        atr = _atr(d)
        # 锚定 VWAP(从窗口起点累计):年轻股缺月/年锚,窗口锚是诚实的参考线
        tp = (_series(d, "High") + _series(d, "Low") + close) / 3
        vol = _series(d, "Volume")
        vwap = float((tp * vol).cumsum().iloc[-1] / vol.cumsum().iloc[-1]) \
            if float(vol.sum()) > 0 else None
        return {
            "interval": "1h",
            "n_bars": int(len(close)),
            "rsi14": round(rsi, 1) if rsi is not None else None,
            "atr14": round(atr, 2) if atr else None,
            "atr_pct": round(atr / price, 4) if atr and price else None,
            "sma20": round(sma20, 2) if sma20 else None,
            "above_sma20": (price > sma20) if sma20 else None,
            "sma50": round(sma50, 2) if sma50 else None,
            "above_sma50": (price > sma50) if sma50 else None,
            "vwap": round(vwap, 2) if vwap else None,
            "above_vwap": (price > vwap) if vwap else None,
        }
    except Exception as e:
        logger.warning(f"spacex intraday failed: {e}")
        return None


def fetch_spacex_peer_prior() -> dict | None:
    """③ 同业波动先验 + 收缩估计:借太空同业一年历史,拉住 SPCX 抖动的 20 根短样本。"""
    try:
        s = yf.download(TICKER, period="1mo", interval="1d",
                        auto_adjust=True, progress=False)["Close"]
        s = s.iloc[:, 0] if hasattr(s, "columns") else s
        n = int(len(s))
        own_vol = float(s.pct_change().std() * np.sqrt(252)) if n > 3 else None
        peers = []
        for p, meta in _PEERS.items():
            try:
                c = yf.download(p, period="1y", interval="1d",
                                auto_adjust=True, progress=False)["Close"]
                c = c.iloc[:, 0] if hasattr(c, "columns") else c
                vol = float(c.pct_change().std() * np.sqrt(252))
                peers.append({"ticker": p, "name": meta["name"],
                              "vol": round(vol, 3), "pure": meta["pure"]})
            except Exception:
                pass
        pure = [x["vol"] for x in peers if x["pure"]]
        prior = float(np.median(pure)) if pure else None
        shrink_w = blended = None
        if own_vol is not None and prior is not None:
            shrink_w = round(n / (n + _SHRINK_K), 3)
            blended = round(shrink_w * own_vol + (1 - shrink_w) * prior, 3)
        return {
            "spcx_own_vol": round(own_vol, 3) if own_vol else None,
            "peer_prior": round(prior, 3) if prior else None,
            "peers": peers,
            "shrink_weight": shrink_w,
            "blended_vol": blended,
            "n_bars": n,
        }
    except Exception as e:
        logger.warning(f"spacex peer prior failed: {e}")
        return None


_SYSTEM = """你是一位专注单一个股 SPCX(Space Exploration Technologies,SpaceX)的交易决策助手。
你的唯一任务:基于给定的实时技术读数、新闻头条和事件日历,给出今天对 SPCX 的可执行判断。

铁律:
1. SPCX 是 2026 年新上市的股票,日线历史极短(~20 根),**日线的 RSI/均线预热失真、
   不可信**。要看技术面,优先用三条不吃日线长度的"抢先量":
   ① 期权隐含波动(前瞻):ATM 跨式给出的预期波动% 与 IV 期限结构 = 市场对未来幅度的
      预测;事件到期(覆盖 8/6)的预期波动就是市场已定价的解禁+财报冲击。IV 偏斜为正
      = 下行恐惧买盘更重。**这是幅度预测,不是方向**。
   ② 盘中 1h 时间框:~130 根,RSI/ATR/均线已预热、可用 —— 技术判断以它为准,别用日线。
   ③ 同业波动先验(收缩后的 blended_vol):设仓位/止损宽度时用它,而非日线 ATR。
   同时,**机械技术位对事件全盲**——事件日历(锁定期解禁/财报)仍是压倒一切的第一优先。
   若解禁临近(数日内),即便技术偏多也要显式下调信心、优先回避供给冲击。
2. 这是一只普通个股、只做多视角(散户直接买卖 SPCX,无配对做空工具)。动作只有三种:
   - "BUY":建仓或加仓做多
   - "HOLD":持有观望,不新开仓
   - "REDUCE":减仓/回避(已持有者了结,空仓者继续等)
3. 不许给出精确的顶/底点位。给锚定的情景区间(入场/止损/目标),并明说确切点位不可知。
4. 全部中文。summary 一句话讲清今天怎么做。
5. 只输出一个 JSON 对象,不要任何解释文字或 markdown 围栏。

JSON 字段:
{
  "action": "BUY"|"HOLD"|"REDUCE",
  "conviction": 0-10 整数,
  "summary": "一句话结论",
  "entry": 数字或null(BUY 时的建议入场;非 BUY 可 null),
  "stop": 数字或null,
  "target": 数字或null,
  "horizon": "如 数日–数周",
  "drivers": [{"factor":"因子名","stance":"bull"|"bear"|"neutral","note":"中文说明"}],  // 3-6 条
  "catalysts_read": "对事件日历的解读,一句话",
  "risks": ["风险1","风险2"],  // 必含锁定期相关
  "lockup_note": "对 2026-08-06 解禁的专门判断",
  "system_notes": ["可选:数据问题或自检"]
}"""


def _build_prompt(data: dict, news: list[dict],
                  options: dict | None = None,
                  intraday: dict | None = None,
                  peer_prior: dict | None = None) -> str:
    def _ma(label, val, above):
        if val is None:
            return f"{label} 数据不足"
        return f"{label} ${val}({'上方' if above else '下方'})"

    def _pct(x):
        return f"{x*100:+.1f}%" if x is not None else "数据不足"

    lines = [
        f"# SPCX 今日快照({data['as_of']},共 {data['n_bars']} 根日线)",
        f"现价 ${data['price']}(较昨收 {data['today_change']*100:+.1f}%),"
        f"历史最高 ${data['ath']} / 最低 ${data['atl']},距历史高点 {data['drawdown_from_ath']*100:+.0f}%。",
        f"52周区间 ${data['low_52w']}–${data['high_52w']}。",
        "均线:" + "、".join([_ma("20日", data["sma20"], data["above_sma20"]),
                             _ma("50日", data["sma50"], data["above_sma50"]),
                             _ma("200日", data["sma200"], data["above_sma200"])]) + "。",
        f"RSI14 {data['rsi14']},ATR14 ${data['atr14']}(≈{(data['atr_pct'] or 0)*100:.1f}%/日),"
        f"近5日 {_pct(data['ret_5d'])} / 近20日 {_pct(data['ret_20d'])},"
        f"今日量能 ×{data['vol_vs_20d']}(vs 20日均量)。",
    ]
    if data.get("thin_data"):
        lines.append(
            f"⚠️ 上市仅 {data['n_bars']} 根日线 —— 上面日线的 RSI/均线预热失真、别信绝对值。"
            f"技术判断请用下面的【盘中1h】与【期权隐含】,风险/仓位用【同业波动先验】。")

    # ① 期权隐含波动(前瞻)
    if options and options.get("term"):
        lines += ["", "# ① 期权隐含波动(前瞻·零历史需求)"]
        for x in options["term"]:
            em = f"±{x['expected_move_pct']*100:.1f}%" if x.get("expected_move_pct") else "—"
            iv = f"{x['atm_iv']*100:.0f}%" if x.get("atm_iv") else "—"
            tag = " ←覆盖8/6事件" if options.get("event_expiry") and x["expiry"] == options["event_expiry"]["expiry"] else ""
            lines.append(f"- 到期 {x['expiry']}(还有{x.get('dte','?')}天):预期波动 {em} · ATM IV {iv}{tag}")
        ev = options.get("event_expiry")
        if ev and ev.get("expected_move_pct"):
            lines.append(f"→ 市场已给 8/6 事件定价:到期 {ev['expiry']} 预期波动 ±{ev['expected_move_pct']*100:.1f}%。")
        sk = options.get("skew_put_minus_call")
        if sk is not None:
            lines.append(f"→ IV 偏斜(看跌−看涨)={sk*100:+.0f} 个点:{'下行恐惧买盘更重' if sk > 0 else '偏追涨/下行担忧不重'}。")

    # ② 盘中 1h(数据充足,技术面以此为准)
    if intraday:
        i = intraday
        lines += ["", f"# ② 盘中 {i['interval']} 时间框({i['n_bars']} 根,已预热·技术面看这个)"]
        lines.append(
            f"RSI14 {i.get('rsi14')} · ATR ${i.get('atr14')}(≈{(i.get('atr_pct') or 0)*100:.1f}%/时)"
            f" · vs 20周期均线 {'上方' if i.get('above_sma20') else '下方'}"
            + (f" · vs 50周期均线 {'上方' if i.get('above_sma50') else '下方'}" if i.get("sma50") else "")
            + (f" · vs 锚定VWAP ${i.get('vwap')} {'上方' if i.get('above_vwap') else '下方'}" if i.get("vwap") else "")
            + "。")

    # ③ 同业波动先验(收缩)
    if peer_prior and peer_prior.get("blended_vol") is not None:
        pp = peer_prior
        peers_s = "、".join(f"{x['ticker']} {x['vol']*100:.0f}%" for x in pp.get("peers", []) if x.get("pure"))
        lines += ["", "# ③ 同业波动先验(设仓位/止损宽度用这个,别用日线 ATR)"]
        lines.append(
            f"SPCX 自算 20日年化波动 {(pp.get('spcx_own_vol') or 0)*100:.0f}%(样本短·不稳);"
            f"纯太空同业中位 {(pp.get('peer_prior') or 0)*100:.0f}%({peers_s});"
            f"收缩权重 {pp.get('shrink_weight')} → **可用波动估计 {(pp.get('blended_vol') or 0)*100:.0f}%**。")

    lines += [
        "",
        f"# 事件日历(as of {_CATALYST_ASOF},需复核)",
    ]
    for c in _CATALYSTS:
        lines.append(f"- 【{c['impact']}】{c['date']} {c['event']}:{c['note']}")
    lines.append("")
    lines.append("# 近3日新闻头条")
    if news:
        for n in news[:7]:
            lines.append(f"- {n['title']}" + (f"({n['source']})" if n.get("source") else ""))
    else:
        lines.append("(无新闻或抓取失败)")
    lines.append("")
    lines.append("请据此输出今天对 SPCX 的 JSON 决策。")
    return "\n".join(lines)


def _sanitize(dec: dict, data: dict) -> dict:
    """夹紧信心、补算 RR、剔除离谱点位。DeepSeek-only,无 Claude 兜底。"""
    dec["action"] = dec.get("action") if dec.get("action") in ("BUY", "HOLD", "REDUCE") else "HOLD"
    dec["conviction"] = max(0, min(10, int(dec.get("conviction", 0) or 0)))
    dec["drivers"] = (dec.get("drivers") or [])[:6]
    dec["risks"] = (dec.get("risks") or [])[:5]
    dec["system_notes"] = (dec.get("system_notes") or [])[:4]

    price = data["price"]
    entry = dec.get("entry")
    stop = dec.get("stop")
    target = dec.get("target")

    def _sane(x):
        return isinstance(x, (int, float)) and price * 0.4 < x < price * 2.5

    entry = float(entry) if _sane(entry) else None
    stop = float(stop) if _sane(stop) else None
    target = float(target) if _sane(target) else None
    dec["entry"], dec["stop"], dec["target"] = entry, stop, target

    rr = None
    if entry and stop and target and entry != stop:
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = round(reward / risk, 2) if risk > 0 else None
    dec["rr"] = rr
    return dec


def generate_spacex_decision(data: dict, news: list[dict],
                             options: dict | None = None,
                             intraday: dict | None = None,
                             peer_prior: dict | None = None) -> dict | None:
    """**只调 DeepSeek V4 Pro**。无 key 或任何失败 → None(不回退 Claude)。"""
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        logger.info("SPCX: no DEEPSEEK_API_KEY — decision skipped (degrades to None)")
        return None
    try:
        import requests
        r = requests.post(_DS_URL, timeout=150, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        }, json={
            "model": _DS_MODEL,
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user", "content": _build_prompt(
                             data, news, options, intraday, peer_prior)}],
            "response_format": {"type": "json_object"},
            "max_tokens": 4000,
            "stream": False,
        })
        r.raise_for_status()
        text = (r.json()["choices"][0]["message"]["content"] or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            text = text[4:] if text.startswith("json") else text
            text = text.rsplit("```", 1)[0]
        dec = json.loads(text)
        dec["model"] = _DS_MODEL
        return _sanitize(dec, data)
    except Exception as e:
        logger.warning(f"SPCX deepseek decision failed: {e}")
        return None


def compute_spacex(force_refresh: bool = False) -> dict:
    """整合 数据 + 新闻 + 三条抢先量 + DeepSeek 决策 → 一个 payload(spacex_state.data)。"""
    data = fetch_spacex_data()
    news = fetch_spacex_news()
    options = fetch_spacex_options(data["price"])       # ① 期权隐含(前瞻)
    intraday = fetch_spacex_intraday()                  # ② 盘中 1h(已预热)
    peer_prior = fetch_spacex_peer_prior()              # ③ 同业波动先验(收缩)
    decision = generate_spacex_decision(data, news, options, intraday, peer_prior)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": _DS_MODEL,
        "data": data,
        "news": news,
        "options": options,
        "intraday": intraday,
        "peer_prior": peer_prior,
        "catalysts": _CATALYSTS,
        "catalyst_asof": _CATALYST_ASOF,
        "decision": decision,          # None = 未生成(无 key / 失败),前端显示占位
    }


def publish_spacex() -> dict:
    """Compute + upsert to Supabase spacex_state id='current'. Shared by daily publish."""
    payload = compute_spacex()
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        try:
            from supabase import create_client
            sb = create_client(url, key)
            safe = json.loads(json.dumps(payload, default=str),
                              parse_constant=lambda _c: None)
              # 2026-08-05:显式带上 updated_at。upsert 只写 `data`,而 `updated_at` 的
            # DEFAULT now() **只在 INSERT 时生效** —— 这一行 id="current" 从建表那天
            # 起就没变过,导致任何拿 updated_at 判新鲜度的人(含 Claude 自己,08-05
            # 排查 PublishFunction 时就被骗过)会看到一个 42 天没更新的假象,
            # 而 data.generated_at 其实每天都在动。监控字段本身骗人比没有更糟。
            sb.table("spacex_state").upsert({"id": "current", "data": safe, "updated_at": _utc_now()}).execute()
        except Exception as e:
            logger.warning(f"publish_spacex write failed: {e}")
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import warnings
    warnings.filterwarnings("ignore")
    out = compute_spacex()
    d = out["data"]
    print(f"SPCX ${d['price']}  距高点 {d['drawdown_from_ath']*100:+.0f}%  "
          f"日线RSI {d['rsi14']}(薄数据={d['thin_data']})")
    op = out.get("options")
    if op:
        ev = op.get("event_expiry") or {}
        print(f"① 期权:近月预期波动 ±{(op.get('near_expected_move_pct') or 0)*100:.1f}% · "
              f"事件到期 {ev.get('expiry')} ±{(ev.get('expected_move_pct') or 0)*100:.1f}% · "
              f"偏斜 {op.get('skew_put_minus_call')}")
    iq = out.get("intraday")
    if iq:
        print(f"② 盘中{iq['interval']}({iq['n_bars']}根):RSI {iq['rsi14']} · "
              f"ATR {(iq.get('atr_pct') or 0)*100:.1f}%/时 · 20周期{'上' if iq.get('above_sma20') else '下'}方")
    pp = out.get("peer_prior")
    if pp:
        print(f"③ 同业先验:自算{(pp.get('spcx_own_vol') or 0)*100:.0f}% + 同业{(pp.get('peer_prior') or 0)*100:.0f}%"
              f" → 收缩后 {(pp.get('blended_vol') or 0)*100:.0f}%(权重{pp.get('shrink_weight')})")
    print(f"新闻 {len(out['news'])} 条")
    dec = out["decision"]
    if dec:
        print(f"决策: {dec['action']} 信心{dec['conviction']}/10 — {dec['summary']}")
    else:
        print("决策: 未生成(无 DEEPSEEK_API_KEY 或调用失败)")
