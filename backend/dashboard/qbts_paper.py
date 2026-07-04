"""
QBTS 冠军策略陪跑(纸面测量)—— 2026-07-03 两轮策略动物园(35 套)的前两名:

  ① QQQ50 × 波动率目标   连续仓位规则 → 虚拟 $1000 净值曲线,每日结算,
     与"死拿"净值并排对照。敞口 = QQQ>50日线 ? clip(0.6/20日年化波动, 0.2, 1) : 0。
     回测:全期 +630% / 近1年 +113% / 回撤 -40%(B&H 同期 +1944%/+52%/-71%)。
  ② 5日swing × QQQ50     事件式 → 同 dip_buy 的状态机。收盘≤5日最低 且 QQQ 在
     50日线上 → $1000 虚拟买入;收盘≥5日最高 → 止盈;10 个交易日到期平仓。
     回测:72%(23/32) / 全期 +554% / 近1年 +75% / 回撤 -39%。
  ③ BTC昨日绿 × QQQ50 × 波目(2026-07-04 第四轮新增)—— BTC 昨天收涨 且 QQQ
     在 50 日线上 → 按波目敞口持有,否则空仓。回测:全期 +611% / 近1年 +120% /
     回撤 -20%(全场最浅),阈值/去过滤/切半全正。BTC 取最近一根**已完成** UTC
     日线;当日 BTC 拉取失败则该台账当天不动(净值口径同 ①,漏日由 prev_close 跨越)。
  ④ CLV强收盘 × QQQ50 × 波目(2026-07-04 第六轮新增)—— CLV=(2C−H−L)/(H−L),
     收盘收在当日区间上部(>0.3)且 QQQ50 顺风 → 按波目敞口持明天,否则空仓。
     回测:近1年 +189% / 回撤 -18%,阈值 0/0.3/0.6 全稳、成本加倍仍 +162%;
     弱点:前半段仅 +47%,偏近期 regime(吃 1d 延续 DNA)。
  ⑤ 配对超涨 veto(2026-07-04 第八轮新增)—— QQQ50×波目 照常,但 QBTS 对
     IONQ 的 log 价差 40日 z>1(贵出 1σ)时清仓等。回测:近1年 +176% /
     回撤 -22%,z 阈值 1.0/1.5/2.0 全部改善;与榜首配对同结构反用。
  ⑥ QTUM昨日绿 × QQQ50 × 波目(2026-07-04 第八轮新增)—— 量子板块 ETF 昨日
     收涨 → 按波目持有。回测:全期 +1102% / 近1年 +228% / 回撤 -19%(领先家
     族最强);注意 QTUM 自含 QBTS 权重,部分是自延续,单次扫描打折看待。
     IONQ / QTUM 拉取失败 → 对应台账当日不动(同 ③ 的 prev_close 跨日口径)。

定位与 dip_buy 相同:**纯纸面测量,不进 edge、不进决策 prompt**,多重比较
折扣照打(35 选 2),攒够样本后用真实成绩决定去留。
持久化:scan_paper 表独立行 id='qbts_champs'(零迁移;本地文件回退);
last_date 幂等,每个交易日只推进一步,漏跑不回填。
QQQ 数据:yfinance 现拉 6mo(publish 每日一次,失败则该日跳过、状态不动)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent.parent / "data" / "cache"
_DIR.mkdir(parents=True, exist_ok=True)
_FILE = _DIR / "qbts_champs.json"
_ROW_ID = "qbts_champs"
_TABLE = "scan_paper"

_USD = 1000.0
_COST = 0.002
_TARGET_VOL = 0.60
_SWING_LOOKBACK = 5
_SWING_MAX_HOLD = 10


def _load() -> dict:
    from dashboard.scan_store import _supabase
    sb = _supabase()
    if sb is not None:
        try:
            rows = sb.table(_TABLE).select("data").eq("id", _ROW_ID).execute().data
            if rows and rows[0].get("data"):
                return rows[0]["data"]
        except Exception as e:
            logger.warning(f"qbts_paper: load failed, using file — {e}")
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text())
        except Exception:
            pass
    return {"volreg": None, "swing": {"open": None, "closed": []}, "last_date": None}


def _save(state: dict) -> None:
    from dashboard.scan_store import _supabase
    sb = _supabase()
    if sb is not None:
        try:
            sb.table(_TABLE).upsert({"id": _ROW_ID, "data": state}).execute()
            return
        except Exception as e:
            logger.warning(f"qbts_paper: save failed, using file — {e}")
    _FILE.write_text(json.dumps(state, ensure_ascii=False))


def _qqq_risk_on() -> "bool | None":
    """QQQ 收盘 vs 自身 50 日线;失败返回 None(该日跳过,不猜)。"""
    try:
        import yfinance as yf
        q = yf.download("QQQ", period="6mo", progress=False)["Close"].squeeze()
        if len(q) < 55:
            return None
        return bool(float(q.iloc[-1]) > float(q.rolling(50).mean().iloc[-1]))
    except Exception as e:
        logger.warning(f"qbts_paper: QQQ fetch failed — {e}")
        return None


def _ionq_z40(qbts_close: pd.Series) -> "float | None":
    """QBTS/IONQ log 价差的 40 日 z;失败返回 None(veto 台账当日不动)。"""
    try:
        import numpy as np
        import yfinance as yf
        i = yf.download("IONQ", period="6mo", progress=False)["Close"].squeeze()
        if i.index.tz is not None:
            i.index = i.index.tz_localize(None)
        qc = qbts_close.copy()
        if getattr(qc.index, "tz", None) is not None:
            qc.index = qc.index.tz_localize(None)
        qc.index = qc.index.normalize()
        i = i.reindex(qc.index).ffill()
        spread = (np.log(qc) - np.log(i)).dropna()
        win = spread.tail(40)
        if len(win) < 30 or float(win.std()) < 1e-9:
            return None
        return float((spread.iloc[-1] - win.mean()) / win.std())
    except Exception as e:
        logger.warning(f"qbts_paper: IONQ fetch failed — {e}")
        return None


def _qtum_green() -> "bool | None":
    """QTUM 最近一个已完成交易日的涨跌;失败返回 None。"""
    try:
        import yfinance as yf
        g = yf.download("QTUM", period="1mo", progress=False)["Close"].squeeze()
        today_et = pd.Timestamp.now(tz="America/New_York").date()
        g = g[[d.date() < today_et for d in g.index]]
        if len(g) < 2:
            return None
        return bool(float(g.iloc[-1]) > float(g.iloc[-2]))
    except Exception as e:
        logger.warning(f"qbts_paper: QTUM fetch failed — {e}")
        return None


def _btc_green() -> "bool | None":
    """最近一根已完成 UTC 日线的 BTC 涨跌;失败返回 None(该台账当日不动)。"""
    try:
        import yfinance as yf
        b = yf.download("BTC-USD", period="1mo", progress=False)["Close"].squeeze()
        b = b[b.index.date < pd.Timestamp.now(tz="UTC").date()]  # 去掉今天的半根
        if len(b) < 2:
            return None
        return bool(float(b.iloc[-1]) > float(b.iloc[-2]))
    except Exception as e:
        logger.warning(f"qbts_paper: BTC fetch failed — {e}")
        return None


def analyze_champs(df_d: pd.DataFrame) -> dict | None:
    """每日调用:推进两个台账一步 + 返回展示块。df_d 需含 close(大小写均可)。"""
    try:
        d = df_d.rename(columns=str.lower)
        if len(d) < 30:
            return None
        c = d["close"].astype(float)
        close = float(c.iloc[-1])
        today = str(pd.Timestamp(df_d.index[-1]).date())
        lo5 = float(c.tail(_SWING_LOOKBACK).min())
        hi5 = float(c.tail(_SWING_LOOKBACK).max())
        rets = c.pct_change()
        vol20 = float(rets.tail(20).std() * (252 ** 0.5))
        vt = max(0.20, min(1.00, _TARGET_VOL / vol20)) if vol20 > 0 else 0.50

        st = _load()
        risk_on = _qqq_risk_on()

        def _advance(key: str, exposure: float) -> dict:
            """净值台账推进一步(与 ①③④ 同口径:昨日敞口吃今日收益,再调仓计费)。"""
            x = st.get(key)
            if x is None:
                x = {"nav": _USD, "start_date": today,
                     "prev_close": close, "exposure": exposure}
            else:
                r = close / x["prev_close"] - 1 if x.get("prev_close") else 0.0
                x["nav"] = x["nav"] * (1 + x.get("exposure", 0.0) * r) \
                    - x["nav"] * abs(exposure - x.get("exposure", 0.0)) * _COST
                x["prev_close"] = close
                x["exposure"] = exposure
            st[key] = x
            return x

        if st.get("last_date") != today and risk_on is not None:
            exposure = vt if risk_on else 0.0
            # ── ① 净值曲线:用昨日敞口吃今天的收益,再调到今日目标敞口 ──
            vr = st.get("volreg")
            if vr is None:
                vr = {"nav": _USD, "bh_nav": _USD, "start_date": today,
                      "prev_close": close, "exposure": exposure}
            else:
                r = close / vr["prev_close"] - 1 if vr.get("prev_close") else 0.0
                vr["nav"] = vr["nav"] * (1 + vr.get("exposure", 0.0) * r) \
                    - vr["nav"] * abs(exposure - vr.get("exposure", 0.0)) * _COST
                vr["bh_nav"] = vr["bh_nav"] * (1 + r)
                vr["prev_close"] = close
                vr["exposure"] = exposure
            st["volreg"] = vr

            # ── ② 5日swing 状态机 ──
            sw = st.get("swing") or {"open": None, "closed": []}
            pos = sw.get("open")
            if pos:
                pos["days"] = int(pos.get("days", 0)) + 1
                exit_px = reason = None
                if close >= hi5:
                    exit_px, reason = close, "破5日新高"
                elif pos["days"] >= _SWING_MAX_HOLD:
                    exit_px, reason = close, "10天到期"
                if exit_px is not None:
                    pnl = pos["shares"] * exit_px * (1 - _COST) - _USD
                    sw["closed"] = (sw.get("closed") or [])[-49:] + [{
                        "entry_date": pos["entry_date"], "entry": pos["entry"],
                        "exit_date": today, "exit": round(exit_px, 2),
                        "days": pos["days"], "reason": reason,
                        "pnl": round(pnl, 2), "pnl_pct": round(pnl / _USD, 4)}]
                    sw["open"] = None
            elif close <= lo5 and risk_on:
                shares = _USD * (1 - _COST) / close
                sw["open"] = {"entry_date": today, "entry": round(close, 2),
                              "shares": round(shares, 4), "days": 0}
            st["swing"] = sw

            # ── ④ CLV强收盘 × QQQ50 × 波目 净值 ──
            if {"high", "low"}.issubset(d.columns):
                hi_t, lo_t = float(d["high"].iloc[-1]), float(d["low"].iloc[-1])
                clv_val = (2 * close - hi_t - lo_t) / (hi_t - lo_t) if hi_t > lo_t else 0.0
                c_exp = vt if (risk_on and clv_val > 0.3) else 0.0
                cv = st.get("clv")
                if cv is None:
                    cv = {"nav": _USD, "start_date": today,
                          "prev_close": close, "exposure": c_exp}
                else:
                    r = close / cv["prev_close"] - 1 if cv.get("prev_close") else 0.0
                    cv["nav"] = cv["nav"] * (1 + cv.get("exposure", 0.0) * r) \
                        - cv["nav"] * abs(c_exp - cv.get("exposure", 0.0)) * _COST
                    cv["prev_close"] = close
                    cv["exposure"] = c_exp
                cv["clv"] = round(clv_val, 2)
                st["clv"] = cv

            # ── ③ BTC昨日绿 × QQQ50 × 波目 净值 ──
            btc_green = _btc_green()
            if btc_green is not None:
                b_exp = vt if (risk_on and btc_green) else 0.0
                bt = st.get("btc")
                if bt is None:
                    bt = {"nav": _USD, "start_date": today,
                          "prev_close": close, "exposure": b_exp}
                else:
                    r = close / bt["prev_close"] - 1 if bt.get("prev_close") else 0.0
                    bt["nav"] = bt["nav"] * (1 + bt.get("exposure", 0.0) * r) \
                        - bt["nav"] * abs(b_exp - bt.get("exposure", 0.0)) * _COST
                    bt["prev_close"] = close
                    bt["exposure"] = b_exp
                bt["btc_green"] = btc_green
                st["btc"] = bt

            # ── ⑤ 配对超涨 veto:QBTS 比 IONQ 贵 1σ 时清仓 ──
            z40 = _ionq_z40(c)
            if z40 is not None:
                x = _advance("veto", vt if (risk_on and z40 <= 1.0) else 0.0)
                x["z40"] = round(z40, 2)

            # ── ⑥ QTUM昨日绿 × QQQ50 × 波目 ──
            qg = _qtum_green()
            if qg is not None:
                x = _advance("qtum", vt if (risk_on and qg) else 0.0)
                x["qtum_green"] = qg

            st["last_date"] = today
            st["risk_on"] = risk_on
            _save(st)

        vr = st.get("volreg")
        sw = st.get("swing") or {}
        closed = sw.get("closed") or []
        n, wins = len(closed), sum(1 for t in closed if t["pnl"] > 0)
        pos = sw.get("open")
        out = {
            "risk_on": st.get("risk_on"),
            "vt_pct": round(vt, 2),
            "volreg": ({
                "nav": round(vr["nav"], 2), "bh_nav": round(vr["bh_nav"], 2),
                "start_date": vr["start_date"],
                "exposure": round(vr.get("exposure", 0.0), 2),
                "ret_pct": round(vr["nav"] / _USD - 1, 4),
                "bh_ret_pct": round(vr["bh_nav"] / _USD - 1, 4),
            } if vr else None),
            "clv": ({
                "nav": round(cv["nav"], 2),
                "start_date": cv["start_date"],
                "exposure": round(cv.get("exposure", 0.0), 2),
                "clv": cv.get("clv"),
                "ret_pct": round(cv["nav"] / _USD - 1, 4),
            } if (cv := st.get("clv")) else None),
            "btc": ({
                "nav": round(bt["nav"], 2),
                "start_date": bt["start_date"],
                "exposure": round(bt.get("exposure", 0.0), 2),
                "btc_green": bt.get("btc_green"),
                "ret_pct": round(bt["nav"] / _USD - 1, 4),
            } if (bt := st.get("btc")) else None),
            "veto": ({
                "nav": round(vx["nav"], 2),
                "start_date": vx["start_date"],
                "exposure": round(vx.get("exposure", 0.0), 2),
                "z40": vx.get("z40"),
                "vetoed": bool((vx.get("z40") or 0) > 1.0),
                "ret_pct": round(vx["nav"] / _USD - 1, 4),
            } if (vx := st.get("veto")) else None),
            "qtum": ({
                "nav": round(qx["nav"], 2),
                "start_date": qx["start_date"],
                "exposure": round(qx.get("exposure", 0.0), 2),
                "qtum_green": qx.get("qtum_green"),
                "ret_pct": round(qx["nav"] / _USD - 1, 4),
            } if (qx := st.get("qtum")) else None),
            "swing": {
                "lo5": round(lo5, 2), "hi5": round(hi5, 2), "close": round(close, 2),
                "would_trigger": bool(close <= lo5),
                "open": None,
                "n_closed": n, "n_win": wins,
                "win_rate": round(wins / n, 3) if n else None,
                "realized": round(sum(t["pnl"] for t in closed), 2),
            },
        }
        if pos:
            unreal = pos["shares"] * close * (1 - _COST) - _USD
            out["swing"]["open"] = {**pos, "unreal": round(unreal, 2),
                                    "unreal_pct": round(unreal / _USD, 4),
                                    "hi5": round(hi5, 2)}
        return out
    except Exception as e:
        logger.warning(f"qbts_paper failed: {e}")
        return None
