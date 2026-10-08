"""用户实盘持仓(💼 当前持仓)。

存 Supabase `scan_paper` 表独立行 id='user_positions'(复用 JSON 行存储,零迁移;
本地文件回退)。每个 ticker 一条,重复添加 = 覆盖更新。**只允许 QBTS/QBTX/QBTZ**
—— 决策大脑是 QBTS 专用系统,别的票它没有任何信号上下文,硬给建议 = 幻觉。

流向:每日 publish 时 `load_positions()` → snapshot['user_positions'] →
decision prompt「用户实盘持仓」段 → 模型逐笔输出 `position_advice`(持有/加仓/
减仓/清仓 + 一句话理由,受执行军规约束)→ 前端 💼 卡展示。站上编辑走
/scan/watch(本地)或 PublishFunction URL(云)的 pos_add / pos_remove 动作,
与自选清单编辑同一条通道。
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED = ("QBTS", "QBTX", "QBTZ")
_TABLE = "scan_paper"
_ROW_ID = "user_positions"
_FILE = Path(__file__).parent.parent / "data" / "cache" / "user_positions.json"


from dashboard.db import supabase as _sb   # 全仓共用一个客户端


def load_positions() -> list[dict]:
    """[{ticker, qty, cost, date}] — Supabase 优先,本地文件回退,失败 = 空表。"""
    sb = _sb()
    if sb is not None:
        try:
            rows = sb.table(_TABLE).select("data").eq("id", _ROW_ID).execute().data
            if rows and rows[0].get("data") is not None:
                return rows[0]["data"].get("positions") or []
        except Exception as e:
            logger.warning(f"positions: load failed, using file — {e}")
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text()).get("positions") or []
        except Exception:
            pass
    return []


def _save(positions: list[dict]) -> None:
    data = {"positions": positions}
    sb = _sb()
    if sb is not None:
        try:
            sb.table(_TABLE).upsert({"id": _ROW_ID, "data": data}).execute()
            return
        except Exception as e:
            logger.warning(f"positions: save failed, using file — {e}")
    _FILE.write_text(json.dumps(data, ensure_ascii=False))


def upsert_position(ticker: str, qty, cost, bought: str | None = None) -> list[dict]:
    """新增/覆盖一笔持仓;返回最新持仓表。bought 缺省 = 今天(用户可回填买入日)。"""
    t = (ticker or "").strip().upper()
    if t not in ALLOWED:
        raise ValueError(f"ticker 仅限 {'/'.join(ALLOWED)}(决策系统只认识它们)")
    qty, cost = float(qty), float(cost)
    if not (qty > 0 and cost > 0):
        raise ValueError("qty/cost 必须为正数")
    pos = [p for p in load_positions() if p.get("ticker") != t]
    pos.append({"ticker": t, "qty": qty, "cost": cost,
                "date": (bought or date.today().isoformat())[:10]})
    pos.sort(key=lambda p: p.get("ticker", ""))
    _save(pos)
    return pos


def remove_position(ticker: str) -> list[dict]:
    t = (ticker or "").strip().upper()
    pos = [p for p in load_positions() if p.get("ticker") != t]
    _save(pos)
    return pos


# ── 推送里的持仓行(2026-10-08 用户点单)──────────────────────────────────
# 10-08 反问:他**主要看推送,很少开网页**,而且 9-08 买的 QBTX 还拿着。持仓原来只进
# 决策 prompt 和网页 💼 卡 —— 他每天真正看的那条收盘心跳里一个字都没有。
# 于是一笔拿了 30 天、军规上限 5 天的 2× ETF,没有任何东西每天提醒他。

_LEV = {"QBTS": 1, "QBTX": 2, "QBTZ": -2}
_MAX_DAYS = 5          # 执行军规 ④:≤5 天用 QBTX/QBTZ,更久用 QBTS 正股


def _px_hist(ticker: str, start: str):
    """买入日以来的日线收盘(yfinance 已按拆/合股调整)。失败 = None。"""
    try:
        import pandas as pd
        import yfinance as yf
        s = (pd.Timestamp(start) - pd.Timedelta(days=7)).date().isoformat()
        h = yf.Ticker(ticker).history(start=s, interval="1d", auto_adjust=False)
        c = h["Close"].dropna()
        if c.empty:
            return None
        c.index = c.index.tz_localize(None).normalize()
        return c
    except Exception as e:
        logger.warning(f"positions: {ticker} 取价失败 — {e}")
        return None


def push_lines(today: date, qbts_closes=None) -> str:
    """每笔持仓一行,给收盘心跳推送用。没持仓 / 全失败 → 空串(不打扰)。

    qbts_closes:心跳已经拉好的 QBTS 日线收盘(算波动拖累用,省一次下载)。"""
    try:
        pos = load_positions()
    except Exception:
        return ""
    if not pos:
        return ""

    sigma2 = None                      # QBTS 20 日对数收益方差(年化)
    try:
        import numpy as np
        if qbts_closes is not None and len(qbts_closes) > 21:
            r = np.log(qbts_closes.astype(float)).diff().dropna().tail(20)
            sigma2 = float(r.var() * 252)
    except Exception:
        sigma2 = None

    out = []
    for p in pos:
        t = p.get("ticker")
        try:
            qty, cost = float(p.get("qty")), float(p.get("cost"))
            bought = str(p.get("date"))[:10]
            held = (today - date.fromisoformat(bought)).days
        except Exception:
            continue
        c = _px_hist(t, bought)
        if c is None:
            out.append(f"💼 {t} {qty:g} 股 @ ${cost:.2f} · 取价失败,今天算不了盈亏")
            continue
        now = float(c.iloc[-1])
        # 合股陷阱:QBTX 2026-09-22 做了 4 股合 1 股。yfinance 的历史价已按合股调整,
        # 用户若填的是合股前的成本($6.50),直接算会得出 +193%。拿成本和买入日收盘
        # 对账,差一倍以上就只报警、不算盈亏 —— 宁可不报,也不能报一个假的大赚。
        on_buy = c[c.index <= str(bought)]
        ref = float(on_buy.iloc[-1]) if len(on_buy) else None
        if ref and not (0.5 <= cost / ref <= 2.0):
            out.append(f"💼 {t} ⚠️ 成本 ${cost:.2f} 和 {bought} 的价格 ${ref:.2f} 对不上 —— "
                       f"中间做过合股/拆股?请在网页持仓卡按合股后的成本和股数重填")
            continue
        pnl = now / cost - 1
        line = (f"💼 {t} {qty:g} 股 @ ${cost:.2f} → ${now:.2f}({pnl:+.1%},"
                f"{'+' if pnl >= 0 else '−'}${abs(now - cost) * qty:,.0f})· 拿了 {held} 天")
        lev = _LEV.get(t, 1)
        if lev != 1:
            over = held - _MAX_DAYS
            line += (f",军规 ≤{_MAX_DAYS} 天(已超 {over} 天)" if over > 0
                     else f",军规 ≤{_MAX_DAYS} 天(还剩 {-over} 天)")
            if sigma2:
                # 日再平衡拖累(相对 L×标的对数收益)= (L²−L)/2 · σ²;2× 是 σ²,−2× 是 3σ²
                drag = (lev * lev - lev) / 2 * sigma2 / 252
                line += f" · 波动拖累约 {drag:.2%}/天"
        out.append(line)
    return "\n".join(out)
