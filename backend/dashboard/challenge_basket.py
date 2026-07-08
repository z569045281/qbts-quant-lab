"""
千元挑战「今日照做」篮子 + 全场杠杆 ETF 扫描(/challenge/lessons 页的活部件)。

复刻本地挑战 bot 的进场纪律,每日算一遍:
  上升趋势 = 收盘 > 50 日线 且 近 5 个交易日收益 > 0(bot 的两条硬门)
  之选     = 合格者中 20 日动量最强的一只(动量口径是对 bot「动量最强」的
             复刻近似 —— bot 源码在仓库外,以页面口径为准)
  照做参考价 = 现收盘 ×1.10 止盈 / ×0.88 止损(bot 的 bracket 比例)

两个范围:
  BASKET   = bot 实际交易的 4 只(挑战规则内,「照做」锚点)
  _UNIVERSE = ~40 只成熟的 2×/3× 长腿杠杆 ETF(指数/板块/商品/海外),
             同一套门槛的全场扫描,按 20 日动量取前 8;
             剔除 20 日均成交额 < $5M 的稀薄品种。
             ⚠️ 多重比较警告:从 40 只里挑最热,比从 4 只里挑更容易接在
             情绪顶上;bot 的「60% 触碰赔率」也没在这个宇宙上校准过 ——
             全场扫描是拓展观察,不是挑战规则的一部分。

纯读数,不下单、不进 edge、不进决策 prompt。没有合格标的时,空仓也是信号。
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

BASKET = ["SOXL", "FNGU", "TQQQ", "LABU"]

# 成熟的长腿杠杆 ETF 宇宙(2×/3×;不含做空腿与单股杠杆——风险类别不同)
_UNIVERSE: dict[str, str] = {
    # 宽基指数 3×
    "TQQQ": "纳指100 3×", "UPRO": "标普500 3×", "SPXL": "标普500 3×",
    "UDOW": "道指 3×", "TNA": "罗素2000 3×", "URTY": "罗素2000 3×", "MIDU": "中盘 3×",
    # 板块/主题 3×
    "SOXL": "半导体 3×", "TECL": "科技 3×", "FNGU": "FANG+ 3×", "BULZ": "创新股 3×",
    "WEBL": "互联网 3×", "LABU": "生科 3×", "CURE": "医疗 3×", "PILL": "制药 3×",
    "FAS": "金融 3×", "DPST": "区域银行 3×", "NAIL": "住建 3×", "DFEN": "军工 3×",
    "DRN": "REITs 3×", "UTSL": "公用事业 3×", "RETL": "零售 3×", "WANT": "可选消费 3×",
    "HIBL": "高贝塔 3×",
    # 能源/商品/贵金属 2×
    "ERX": "能源 2×", "GUSH": "油气开采 2×", "NUGT": "金矿 2×", "JNUG": "小金矿 2×",
    "UCO": "原油 2×", "BOIL": "天然气 2×", "AGQ": "白银 2×", "UGL": "黄金 2×",
    # 债券/海外
    "TMF": "20年美债 3×", "YINN": "中国 3×", "CWEB": "中概互联 2×", "CHAU": "A股 2×",
    "EDC": "新兴市场 3×", "INDL": "印度 2×", "EURL": "欧洲 2×", "BRZU": "巴西 2×",
    "KORU": "韩国 3×", "MEXX": "墨西哥 2×",
}

_TP_PCT = 0.10
_STOP_PCT = 0.12
_MIN_ADV = 5_000_000  # 20日均成交额下限(全场扫描的流动性门)
_TOP_N = 8


def _stats(c: pd.Series, v: "pd.Series | None") -> dict | None:
    """单只 ETF 的趋势门读数;数据不足返回 None。"""
    c = c.dropna()
    if len(c) < 55:
        return None
    close = float(c.iloc[-1])
    ma50 = float(c.rolling(50).mean().iloc[-1])
    week_ret = float(close / c.iloc[-6] - 1)
    mom20 = float(close / c.iloc[-21] - 1)
    adv20 = None
    if v is not None:
        dv = (v.reindex(c.index) * c).dropna().tail(20)
        adv20 = float(dv.mean()) if len(dv) else None
    return {
        "close": round(close, 2),
        "ma50": round(ma50, 2),
        "above_50dma": bool(close > ma50),
        "week_ret": round(week_ret, 4),
        "mom20": round(mom20, 4),
        "uptrend": bool(close > ma50 and week_ret > 0),
        "tp": round(close * (1 + _TP_PCT), 2),
        "stop": round(close * (1 - _STOP_PCT), 2),
        "adv20": round(adv20) if adv20 is not None else None,
    }


def analyze_challenge_basket() -> dict | None:
    """篮子 4 只 + 全场杠杆宇宙的趋势门/动量排名/bracket 参考价;失败返回 None。"""
    try:
        import yfinance as yf
        tickers = sorted(set(_UNIVERSE) | set(BASKET))
        raw = yf.download(" ".join(tickers), period="6mo", interval="1d",
                          progress=False, auto_adjust=True, group_by="ticker")

        all_stats: dict[str, dict] = {}
        as_of = None
        for t in tickers:
            try:
                sub = raw[t]
                s = _stats(sub["Close"], sub.get("Volume"))
                if s is None:
                    continue
                s["ticker"] = t
                s["label"] = _UNIVERSE.get(t, "")
                all_stats[t] = s
                if as_of is None:
                    as_of = str(pd.Timestamp(sub["Close"].dropna().index[-1]).date())
            except Exception as e:
                logger.warning(f"challenge_basket: {t} failed — {e}")

        # ── 篮子(bot 实际交易范围,永远 4 行全显示)──
        etfs = [all_stats.get(t) or {"ticker": t, "error": "数据不足"} for t in BASKET]
        ok = [e for e in etfs if e.get("uptrend")]
        pick = max(ok, key=lambda e: e["mom20"])["ticker"] if ok else None

        # ── 全场扫描(同门槛 + 流动性门,动量前 N)──
        liquid = [s for s in all_stats.values()
                  if (s.get("adv20") or 0) >= _MIN_ADV]
        m_ok = sorted([s for s in liquid if s["uptrend"]],
                      key=lambda s: s["mom20"], reverse=True)
        market = {
            "n_scanned": len(liquid),
            "n_qualified": len(m_ok),
            "top": m_ok[:_TOP_N],
            "pick": m_ok[0]["ticker"] if m_ok else None,
            "note": (f"同一套门槛扫 {len(liquid)} 只成熟 2×/3× 长腿杠杆 ETF"
                     f"(剔除20日均成交额<$5M);⚠️ 从全场挑最热比从 4 只里挑"
                     f"更容易接在情绪顶上,且 60% 触碰赔率未在这个宇宙上校准过 ——"
                     f"拓展观察,不是挑战规则。"),
        }

        return {
            "as_of": as_of,
            "etfs": etfs,
            "pick": pick,
            "n_qualified": len(ok),
            "market": market,
            "note": ("合格=收盘>50日线且近一周上涨;之选=合格中20日动量最强"
                     "(bot 动量口径的复刻近似)。无合格标的=按纪律空仓等待。"),
        }
    except Exception as e:
        logger.warning(f"challenge_basket failed: {e}")
        return None
