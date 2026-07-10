"""策略战绩复算(🏇 /factors 页,2026-07-08 起替代因子排行榜)。

把七匹在册纸面马的规则在**全部缓存历史**(QBTS 日线 ~500 根)上重放,产出:
  - trades[]  历史进出段(买入/卖出日期与收盘价、段收益、持有天数)
  - stats     全期/近1年收益、最大回撤、段数、胜率
  - current   当前状态(在场/空仓、敞口、入场价、浮动)

规则与 qbts_paper 台账同源(0.2%/边成本、收盘定仓吃次日收益);数字口径与
mining.md 回测一致。**这是回测复算,不是实盘记录** —— 实盘记录在马厩台账,
页面必须标注这一点。按最后 bar 日期做 JSON 文件缓存(每个交易日只算一次;
外部数据 QQQ/BTC/QTUM/IONQ 各拉一次 2y)。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()   # 独立运行时也要有 FRED_API_KEY(审判工具同款教训:环境变量缺失会静默降级)

logger = logging.getLogger(__name__)

_COST = 0.002
_CACHE = Path(__file__).parent.parent / "data" / "cache" / "strategy_replay.json"
_REL_CACHE = Path(__file__).parent.parent / "data" / "cache" / "release_days.json"
_GPR_CACHE = Path(__file__).parent.parent / "data" / "cache" / "gpr_daily.xls"


def _release_days() -> set[str] | None:
    """CPI+PPI 官方发布日(FRED release dates,含已排期的未来日 → 观察⑧的
    "明天是否公布日"当前仓位才不瞎)。缓存 24h;无 key/失败 → None(跳过该策略)。"""
    if _REL_CACHE.exists() and time.time() - _REL_CACHE.stat().st_mtime < 86400:
        try:
            return set(json.loads(_REL_CACHE.read_text()))
        except Exception:
            pass
    key = os.getenv("FRED_API_KEY")
    if not key:
        return None
    days: set[str] = set()
    try:
        for rid in (10, 46):        # CPI / PPI
            url = (f"https://api.stlouisfed.org/fred/release/dates?release_id={rid}"
                   f"&api_key={key}&file_type=json&limit=1000&sort_order=desc"
                   f"&realtime_start=2022-01-01&realtime_end=2027-12-31"
                   f"&include_release_dates_with_no_data=true")
            with urllib.request.urlopen(url, timeout=15) as r:
                days |= {d["date"] for d in json.load(r).get("release_dates", [])}
        _REL_CACHE.write_text(json.dumps(sorted(days)))
        return days
    except Exception as e:
        logger.warning(f"replay: FRED release dates failed — {e}")
        return None


def _gpr_act() -> pd.Series | None:
    """GPR 日频军事行动分项(Caldara–Iacoviello,免费 xls)。缓存 24h;
    需要 xlrd;失败 → None(跳过观察⑩)。注意数据出版滞后 ~1-2 天。"""
    try:
        if not (_GPR_CACHE.exists() and time.time() - _GPR_CACHE.stat().st_mtime < 86400):
            req = urllib.request.Request(
                "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls",
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                _GPR_CACHE.write_bytes(r.read())
        g = pd.read_excel(_GPR_CACHE)[["date", "GPRD_ACT"]]
        g["date"] = pd.to_datetime(g["date"])
        return g.set_index("date")["GPRD_ACT"].sort_index()
    except Exception as e:
        logger.warning(f"replay: GPR fetch/parse failed — {e}")
        return None


def _dl(ticker: str) -> pd.Series | None:
    try:
        import yfinance as yf
        s = yf.download(ticker, period="2y", interval="1d",
                        auto_adjust=True, progress=False)["Close"].squeeze()
        if s is None or len(s) < 60:
            return None
        if s.index.tz is not None:
            s.index = s.index.tz_localize(None)
        return s
    except Exception as e:
        logger.warning(f"replay: {ticker} fetch failed — {e}")
        return None


def _nav_stats(sret: pd.Series) -> dict:
    nav = (1 + sret.fillna(0)).cumprod()
    dd = float((nav / nav.cummax() - 1).min())
    n1y = nav.iloc[-min(253, len(nav)):]
    w0 = min(60, len(nav) - 1)          # 扣指标热身,与 mining.md 回测同口径
    return {
        "ret_full": round(float(nav.iloc[-1] / nav.iloc[w0] - 1), 4),
        "ret_1y": round(float(n1y.iloc[-1] / n1y.iloc[0] - 1), 4),
        "max_dd": round(dd, 4),
    }, nav


def _segments(w: pd.Series, c: pd.Series, nav: pd.Series) -> list[dict]:
    """连续仓位 w>0 的进出段:买=w 由 0 转正那天的收盘,卖=归零那天的收盘。
    段收益用 NAV 比值(含真实仓位与成本),不是裸价差。"""
    out, in_i = [], None
    active = (w > 0).values
    for i in range(len(w)):
        if active[i] and in_i is None:
            in_i = i
        elif not active[i] and in_i is not None:
            out.append((in_i, i)); in_i = None
    if in_i is not None:
        out.append((in_i, None))
    trades = []
    for a, b in out:
        e = {"buy_date": str(c.index[a].date()), "buy_px": round(float(c.iloc[a]), 2)}
        if b is None:
            e |= {"open": True, "days": int(len(c) - 1 - a),
                  "ret": round(float(nav.iloc[-1] / nav.iloc[a] - 1), 4)}
        else:
            e |= {"open": False, "sell_date": str(c.index[b].date()),
                  "sell_px": round(float(c.iloc[b]), 2), "days": int(b - a),
                  "ret": round(float(nav.iloc[b] / nav.iloc[a] - 1), 4)}
        trades.append(e)
    return trades


def _pack(key, name, emoji, rule, w, c, extra_current=None) -> dict:
    ret = c.pct_change()
    sret = w.shift(1).fillna(0) * ret - _COST * w.diff().abs().fillna(0)
    stats, nav = _nav_stats(sret)
    trades = _segments(w, c, nav)
    closed = [t for t in trades if not t["open"]]
    wins = sum(1 for t in closed if t["ret"] > 0)
    cur_w = float(w.iloc[-1])
    cur = {"in_market": cur_w > 0, "exposure": round(cur_w, 2)}
    if trades and trades[-1]["open"]:
        cur |= {"since": trades[-1]["buy_date"], "entry_px": trades[-1]["buy_px"],
                "unreal": trades[-1]["ret"]}
    if extra_current:
        cur |= extra_current
    return {
        "key": key, "name": name, "emoji": emoji, "rule": rule,
        "stats": stats | {"n_trades": len(closed), "n_wins": wins,
                          "win_rate": round(wins / len(closed), 3) if closed else None},
        "current": cur,
        "trades": trades[::-1][:12],          # 最新在前,最多 12 段
        "n_trades_total": len(trades),
    }


def compute_replay(df_d: pd.DataFrame) -> dict | None:
    d = df_d.rename(columns=str.lower)
    if len(d) < 130 or not {"high", "low", "close"}.issubset(d.columns):
        return None
    c, h, l = d["close"].astype(float), d["high"].astype(float), d["low"].astype(float)
    idx = c.index
    as_of = str(pd.Timestamp(idx[-1]).date())

    # 缓存:同一根 bar 只算一次
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("as_of") == as_of:
                return cached
        except Exception:
            pass

    ret = c.pct_change()
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    vt = (0.60 / vol20).clip(0.20, 1.00).fillna(0.5)

    qqq = _dl("QQQ")
    if qqq is None:
        return None
    qqq = qqq.reindex(idx).ffill()
    risk_on = (qqq > qqq.rolling(50).mean()).fillna(False)

    strategies = []

    # ① QQQ50×波动率目标
    strategies.append(_pack(
        "volreg", "QQQ50×波动率目标", "🥇",
        "QQQ 在 50 日线上才在场;仓位 = 0.6÷QBTS波动率(20%~100%)。回撤保护地基,三票交叉验证 3/3。",
        risk_on.astype(float) * vt, c))

    # ② 5日swing×QQQ50(事件式)
    lo5, hi5 = c.rolling(5).min(), c.rolling(5).max()
    pos, days, sw = 0.0, 0, []
    for i in range(len(c)):
        if pos > 0 and (c.iloc[i] >= hi5.iloc[i - 1] or days >= 10):
            pos, days = 0.0, 0
        elif pos == 0 and i > 5 and c.iloc[i] <= lo5.iloc[i - 1] and risk_on.iloc[i]:
            pos, days = 1.0, 0
        elif pos > 0:
            days += 1
        sw.append(pos)
    strategies.append(_pack(
        "swing", "5日swing×QQQ50", "🥈",
        "绿灯时收盘创5日新低买入;弹回5日新高或满10天卖出。无止损(回测:加止损毁掉它)。胜率~72%,三票 3/3。",
        pd.Series(sw, index=idx), c))

    # ③ BTC 昨日绿 ×QQQ50×波目
    btc = _dl("BTC-USD")
    if btc is not None:
        # 第四轮口径:BTC 收盘序列先对齐交易日(周一含周末),信号(t) 吃 t+1 收益
        # (_pack 里统一 shift(1));多 shift 一天会把 1 天领先的肉全挪没。
        bg = (btc.reindex(idx).ffill().pct_change() > 0).fillna(False)
        strategies.append(_pack(
            "btc", "BTC昨日绿×QQQ50", "🆕",
            "BTC 昨天收涨且绿灯 → 按波目持有;否则空仓。回撤全场最浅(−20%),QBTS 是它最佳宿主。",
            (bg & risk_on).astype(float) * vt, c))

    # ④ CLV 强收盘 ×QQQ50×波目
    clv = ((2 * c - h - l) / (h - l).replace(0, np.nan)).fillna(0)
    strategies.append(_pack(
        "clv", "CLV强收盘×QQQ50", "🆕",
        "昨天收盘收在当日区间上部(CLV>0.3)且绿灯 → 持有今天。吃 1 天惯性;交叉验证 0/3,QBTS 特有,打折看。",
        ((clv > 0.3) & risk_on).astype(float) * vt, c))

    # ⑤ 配对超涨 veto
    ionq = _dl("IONQ")
    if ionq is not None:
        spread = (np.log(c) - np.log(ionq.reindex(idx).ffill())).dropna()
        z40 = ((spread - spread.rolling(40).mean()) / spread.rolling(40).std()).reindex(idx)
        strategies.append(_pack(
            "veto", "配对超涨veto", "🆕",
            "照①做,但 QBTS 比 IONQ 贵出1σ(40日z>1)时强制清仓等。交叉验证 0/3,QBTS 特有,打折看。",
            (risk_on & (z40 <= 1.0).fillna(True)).astype(float) * vt, c,
            extra_current={"z40": round(float(z40.iloc[-1]), 2) if pd.notna(z40.iloc[-1]) else None}))

    # ⑥ QTUM 板块昨日绿
    qtum = _dl("QTUM")
    if qtum is not None:
        qg = (qtum.reindex(idx).ffill().pct_change() > 0).fillna(False)   # 同 BTC 口径
        strategies.append(_pack(
            "qtum", "QTUM板块绿×QQQ50", "🆕",
            "量子板块 ETF 昨天收涨且绿灯 → 按波目持有。注意 QTUM 自含 QBTS 权重,榜首数字有水分。",
            (qg & risk_on).astype(float) * vt, c))

    # ⑦ 特调双腿(事件式)
    def wpr(n):
        hh, ll = h.rolling(n).max(), l.rolling(n).min()
        return (hh - c) / (hh - ll).replace(0, np.nan) * -100
    f_, s_ = wpr(22), wpr(112).rolling(3).mean()
    buy = ((f_ > -80) & (f_.shift(1) <= -80) & (s_ < -50)).fillna(False)
    sell = (((f_ < -20) & (f_.shift(1) >= -20) & (s_ >= -20)) |
            ((f_ < -50) & (f_.shift(1) >= -50) & (s_ < -20))).fillna(False)
    pos, tj = 0.0, []
    for i in range(len(c)):
        if pos > 0 and sell.iloc[i]:
            pos = 0.0
        elif pos == 0 and buy.iloc[i]:
            pos = 1.0
        tj.append(pos)
    strategies.append(_pack(
        "tj", "特调双腿(用户自创)", "🎯",
        "快%R上穿−80且慢<−50 → 抄底买入;快%R下穿−20(止盈)或下穿−50(破位)→ 卖出。进场腿十三轮最强(+17.4%/5天),QBTS 专用。",
        pd.Series(tj, index=idx), c))

    # ── 👀 观察组:观察名单候选的前向战绩(未晋升纸面马,8/15 审判時复查)──
    # 与七马同框展示但 tier="watch";规则文字必须写明出身轮次与没晋升的原因。

    # ⑧ CPI+PPI 公布日(第十六轮:三窗口正+姐妹3/3,卡在 t=1.76<2)
    try:
        rel = _release_days()
        if rel:
            flag = pd.Series([1.0 if str(t.date()) in rel else 0.0 for t in idx], index=idx)
            # 持有"进"公布日 = 前一交易日收盘建仓 → w(t-1)=1 吃公布日收益
            w_rel = flag.shift(-1).fillna(0.0)
            strategies.append(_pack(
                "obs_cpippi", "CPI+PPI公布日", "👀",
                "每月 CPI/PPI 公布日(盘前8:30出数)前一天收盘买、公布日收盘卖,吃公布风险溢价。"
                "第十六轮:全样本+223%/姐妹3/3,但 t=1.76 未过 2.0 晋升线且溢价大半是隔夜漂移马甲"
                "——观察中,别当在册信号。",
                w_rel, c) | {"tier": "watch"})
    except Exception as e:
        logger.warning(f"replay: obs_cpippi skipped — {e}")

    # ⑨ 周一·周末BTC大绿(第十三轮幅度分档:肉集中在 w≥+1.9% 的大绿档)
    try:
        if btc is not None and "open" in d.columns:
            o = d["open"].astype(float)
            flags = []
            for t in idx:
                if t.weekday() != 0:
                    flags.append(False); continue
                b_fri = btc.asof(t - pd.Timedelta(days=3))
                b_sun = btc.asof(t - pd.Timedelta(days=1))
                flags.append(bool(pd.notna(b_fri) and pd.notna(b_sun)
                                  and b_sun / b_fri - 1 >= 0.019))
            flags = pd.Series(flags, index=idx)
            ir = (c / o - 1).where(flags, 0.0) - _COST * 2 * flags.astype(float)
            stats, nav = _nav_stats(ir)
            trades = [{"buy_date": str(t.date()), "buy_px": round(float(o.loc[t]), 2),
                       "open": False, "sell_date": str(t.date()),
                       "sell_px": round(float(c.loc[t]), 2), "days": 0,
                       "ret": round(float(c.loc[t] / o.loc[t] - 1 - _COST * 2), 4)}
                      for t in idx[flags.values]]
            wins = sum(1 for t in trades if t["ret"] > 0)
            strategies.append({
                "key": "obs_btcmon", "name": "周一BTC大绿日内", "emoji": "👀", "tier": "watch",
                "rule": "周末BTC(五→日)涨幅≥+1.9%(大绿档)→ 周一开盘买、收盘卖,不过夜。"
                        "第十三轮:小绿档无肉(+0.36%),大绿档日内+3.08%;效应 2025 年中才出现,"
                        "regime 现象——观察中。",
                "stats": stats | {"n_trades": len(trades), "n_wins": wins,
                                  "win_rate": round(wins / len(trades), 3) if trades else None},
                "current": {"in_market": False, "exposure": 0.0,
                            "triggered_today": bool(flags.iloc[-1])},
                "trades": trades[::-1][:12], "n_trades_total": len(trades),
            })
    except Exception as e:
        logger.warning(f"replay: obs_btcmon skipped — {e}")

    # ⑩ GPR 地缘缓和买入(第十四轮:QTUM 9/9 阈值组合全正,QBTS 单票噪声大)
    try:
        act = _gpr_act()
        if act is not None and len(act) > 60:
            ratio = act / act.rolling(30).median()
            hot = (ratio > 2.5) & (act > 150)
            was = hot.shift(1).rolling(5).max() == 1
            cool = (ratio < 1.2) & was
            cool &= ~cool.shift(1, fill_value=False)
            w_gpr = pd.Series(0.0, index=idx)
            for d0 in act.index[cool]:
                i = int(idx.searchsorted(d0)) + 2   # GPR 出版滞后 ~2 天,+2 才可执行
                if i < len(idx):
                    w_gpr.iloc[i:min(i + 5, len(idx))] = 1.0
            strategies.append(_pack(
                "obs_gprcool", "地缘缓和买入", "👀",
                "军事行动指数(GPR_ACT)跳变后首次回落基线 → 滞后2天买入持5天(枪声停了买)。"
                "第十四轮:QTUM 9 组阈值全正(t最高3.3),QBTS 单票被逼空长尾污染+数据滞后"
                "——观察中,信号极稀(约季度一次)。",
                w_gpr, c) | {"tier": "watch"})
    except Exception as e:
        logger.warning(f"replay: obs_gprcool skipped — {e}")

    # ⑪ 杠杆ETF超卖回归(2026-07-10 适用域研究:与 QBTS 无关的宇宙 —— 仪表盘
    #    通用信号 DNA 的真主场是指数超卖回归;12ETF pooled t=3.0、样本外 8ETF 复现。
    #    这里前向验证可交易版:任一收盘下穿 NW 买入线 → 收盘买入,持 10 个交易日,
    #    同时只持一仓(多票同触发选超卖最深)。)
    try:
        from dashboard.nadaraya_watson import (_H, _LEVEL, _MIN_BARS, _MULT,
                                               _causal_nw)
        univ = ["TQQQ", "SOXL", "UPRO", "TNA", "SPXL", "FNGU"]
        sigs = {}
        for tk in univ:
            s = _dl(tk)
            if s is None or len(s) < _MIN_BARS + 60:
                continue
            nw = pd.Series(_causal_nw(s.to_numpy(float), _H, 499), index=s.index)
            mae = (s - nw).abs().rolling(499, min_periods=_MIN_BARS).mean() * _MULT
            up_, lo_ = nw + mae, nw - mae
            bl = up_ - (up_ - lo_) * _LEVEL / 100.0
            sigs[tk] = {"c": s, "cross": (s < bl) & (s.shift(1) >= bl.shift(1)),
                        "depth": (bl - s) / s}
        if len(sigs) >= 4:                      # 宇宙缺票太多就跳过,别出瘸腿卡
            cal = None
            for v in sigs.values():
                cal = v["c"].index if cal is None else cal.intersection(v["c"].index)
            px2 = pd.DataFrame({t: v["c"] for t, v in sigs.items()}).loc[cal]
            ret2 = px2.pct_change().fillna(0.0)
            cross2 = pd.DataFrame({t: v["cross"] for t, v in sigs.items()}
                                  ).reindex(cal).fillna(False)
            depth2 = pd.DataFrame({t: v["depth"] for t, v in sigs.items()}).reindex(cal)
            HOLD = 10
            sret2 = pd.Series(0.0, index=cal)
            tr2, held = [], None
            for i in range(len(cal)):
                if held is not None:
                    sym = held["sym"]
                    sret2.iloc[i] += float(ret2[sym].iloc[i])
                    if i - held["i0"] >= HOLD:
                        sret2.iloc[i] -= _COST
                        po = float(px2[sym].iloc[i])
                        tr2.append({"sym": sym,
                                    "buy_date": str(cal[held["i0"]].date()),
                                    "buy_px": round(held["px"], 2), "open": False,
                                    "sell_date": str(cal[i].date()),
                                    "sell_px": round(po, 2), "days": i - held["i0"],
                                    "ret": round(po / held["px"] - 1 - 2 * _COST, 4)})
                        held = None
                if held is None and bool(cross2.iloc[i].any()):
                    sym = depth2.iloc[i].where(cross2.iloc[i]).idxmax()
                    if isinstance(sym, str):
                        held = {"sym": sym, "i0": i, "px": float(px2[sym].iloc[i])}
                        sret2.iloc[i] -= _COST
            if held is not None:
                sym = held["sym"]
                tr2.append({"sym": sym, "buy_date": str(cal[held["i0"]].date()),
                            "buy_px": round(held["px"], 2), "open": True,
                            "days": int(len(cal) - 1 - held["i0"]),
                            "ret": round(float(px2[sym].iloc[-1]) / held["px"] - 1
                                         - _COST, 4)})
            stats2, _nav2 = _nav_stats(sret2)
            wins2 = sum(1 for t in tr2 if not t["open"] and t["ret"] > 0)
            closed2 = sum(1 for t in tr2 if not t["open"])
            cur2 = {"in_market": held is not None, "exposure": 1.0 if held else 0.0}
            if held is not None:
                cur2 |= {"sym": held["sym"], "since": tr2[-1]["buy_date"],
                         "entry_px": tr2[-1]["buy_px"], "unreal": tr2[-1]["ret"]}
            strategies.append({
                "key": "obs_levmr", "name": "杠杆ETF超卖回归", "emoji": "👀",
                "tier": "watch",
                "rule": "六只杠杆指数ETF(TQQQ/SOXL/UPRO/TNA/SPXL/FNGU)任一收盘跌破"
                        "非重绘NW包络买入线 → 收盘买入(多票同触发选超卖最深),持10个"
                        "交易日,同时只持一仓。出身:07-10适用域研究——指数超卖回归是"
                        "仪表盘通用信号的真主场(12ETF合并 t=3.0,样本外8ETF复现,妖股上"
                        "同信号为负)。与QBTS完全无关的宇宙,前向观察兑现度。",
                "stats": stats2 | {"n_trades": closed2, "n_wins": wins2,
                                   "win_rate": round(wins2 / closed2, 3) if closed2 else None},
                "current": cur2,
                "trades": tr2[::-1][:12], "n_trades_total": len(tr2),
            })
    except Exception as e:
        logger.warning(f"replay: obs_levmr skipped — {e}")

    # B&H 基准
    bh_stats, _ = _nav_stats(ret)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": as_of,
        "window_start": str(pd.Timestamp(idx[0]).date()),
        "bh": bh_stats,
        "strategies": strategies,
    }
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(out, ensure_ascii=False))
    except Exception:
        pass
    return out
