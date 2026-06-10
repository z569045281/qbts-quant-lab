"""
Alpaca Paper Trading Execution Engine.

Flow per execution:
  1. Find best non-overfit factor from leaderboard
  2. Re-run compute_factor() on fresh QBTS OHLCV
  3. Read latest bar signal → {1: BUY, -1: SELL, 0: HOLD}
  4. Compare with current Alpaca position
  5. Submit market order if needed (long-only, 50% cash sizing)
  6. Return structured result for SSE streaming
"""

import os
import logging
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

TICKER           = "QBTS"
POSITION_SIZE_PCT = 0.50   # fraction of available cash per trade

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest
    _ALPACA_OK = True
except ImportError:
    _ALPACA_OK = False
    logger.warning("alpaca-py not installed — trading disabled")


# ── configuration check ─────────────────────────────────────────────────────

def is_configured() -> bool:
    return bool(
        _ALPACA_OK
        and os.getenv("ALPACA_API_KEY")
        and os.getenv("ALPACA_SECRET_KEY")
    )


def get_trading_client():
    return TradingClient(
        os.environ["ALPACA_API_KEY"],
        os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )


def get_data_client():
    return StockHistoricalDataClient(
        os.environ["ALPACA_API_KEY"],
        os.environ["ALPACA_SECRET_KEY"],
    )


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass
class AccountInfo:
    portfolio_value: float
    cash:            float
    buying_power:    float
    daily_pnl:       float
    daily_pnl_pct:   float   # percent, e.g. 1.23 means +1.23%

    def to_dict(self): return asdict(self)


@dataclass
class PositionInfo:
    qty:             float
    side:            str    # "long" | "flat"
    avg_entry_price: float
    current_price:   float
    market_value:    float
    unrealized_pl:   float
    unrealized_plpc: float  # percent

    def to_dict(self): return asdict(self)


# ── account & position ───────────────────────────────────────────────────────

def get_account(tc) -> AccountInfo:
    acc        = tc.get_account()
    equity     = float(acc.equity)
    last_eq    = float(acc.last_equity)
    return AccountInfo(
        portfolio_value = round(equity, 2),
        cash            = round(float(acc.cash), 2),
        buying_power    = round(float(acc.buying_power), 2),
        daily_pnl       = round(equity - last_eq, 2),
        daily_pnl_pct   = round((equity - last_eq) / last_eq * 100, 3) if last_eq else 0.0,
    )


def get_position(tc, ticker: str = TICKER) -> Optional[PositionInfo]:
    try:
        pos = tc.get_open_position(ticker)
        qty = float(pos.qty)
        return PositionInfo(
            qty             = qty,
            side            = "long" if qty > 0 else "flat",
            avg_entry_price = round(float(pos.avg_entry_price), 4),
            current_price   = round(float(pos.current_price), 4),
            market_value    = round(float(pos.market_value), 2),
            unrealized_pl   = round(float(pos.unrealized_pl), 2),
            unrealized_plpc = round(float(pos.unrealized_plpc) * 100, 3),
        )
    except Exception:
        return None


def get_latest_price(dc, ticker: str = TICKER) -> float:
    try:
        resp = dc.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=ticker)
        )
        q = resp[ticker]
        return round((float(q.ask_price) + float(q.bid_price)) / 2, 4)
    except Exception:
        return 0.0


# ── signal computation ───────────────────────────────────────────────────────

def compute_latest_signal(factor_entry: dict, df) -> dict:
    """
    Re-run a stored factor's code on fresh OHLCV data.
    Returns { value, label, factor_name, factor_score }.
    """
    import numpy as np, pandas as pd

    code = factor_entry.get("code", "")
    if not code:
        return {"value": 0, "label": "HOLD", "error": "no code stored"}

    ns: dict = {"pd": pd, "np": np}
    exec(compile(code, "<factor>", "exec"), ns)
    series   = ns["compute_factor"](df.copy())
    raw      = int(series.iloc[-1])
    label    = {1: "BUY", -1: "SELL", 0: "HOLD"}.get(raw, "HOLD")

    return {
        "value":        raw,
        "label":        label,
        "factor_name":  factor_entry.get("name", "unknown"),
        "factor_score": factor_entry.get("score", 0),
        "freq":         factor_entry.get("freq", "1d"),
    }


# ── order execution ──────────────────────────────────────────────────────────

def execute_signal(tc, dc, signal: int, ticker: str = TICKER) -> list[dict]:
    """
    Long-only market orders.
    signal  1  → BUY  (if flat)
    signal -1  → SELL (if long)
    signal  0  → SELL (if long) / stay flat
    """
    pos     = get_position(tc, ticker)
    acc     = get_account(tc)
    is_long = pos is not None and pos.qty > 0
    results = []

    if signal == 1:
        if is_long:
            results.append({"action": "hold",
                            "msg": f"已持有 {pos.qty:.0f} 股，无需操作"})
        else:
            price  = get_latest_price(dc, ticker)
            if price <= 0:
                results.append({"action": "error", "msg": "无法获取当前价格"})
                return results
            budget = acc.cash * POSITION_SIZE_PCT
            qty    = max(1, int(budget / price))
            order  = tc.submit_order(MarketOrderRequest(
                symbol=ticker, qty=qty,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            ))
            results.append({
                "action":   "buy",
                "qty":      qty,
                "price":    price,
                "order_id": str(order.id),
                "msg":      f"✅ 买入 {qty} 股 {ticker} @ ~${price:.2f}  (预算 ${budget:.0f})",
            })

    elif signal in (-1, 0):
        if is_long:
            qty   = int(abs(pos.qty))
            order = tc.submit_order(MarketOrderRequest(
                symbol=ticker, qty=qty,
                side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
            ))
            results.append({
                "action":   "sell",
                "qty":      qty,
                "order_id": str(order.id),
                "msg":      f"✅ 卖出 {qty} 股 {ticker}  (平多仓)",
            })
        else:
            results.append({"action": "flat",
                            "msg": "已空仓，无需操作"})

    return results


# ── order history ────────────────────────────────────────────────────────────

def get_recent_orders(tc, ticker: str = TICKER, limit: int = 15) -> list[dict]:
    try:
        orders = tc.get_orders(GetOrdersRequest(
            symbols=[ticker],
            status=QueryOrderStatus.ALL,
            limit=limit,
        ))
        return [
            {
                "id":               str(o.id)[:8],
                "created_at":       str(o.created_at)[:16].replace("T", " "),
                "side":             o.side.value.upper(),
                "qty":              float(o.qty or 0),
                "filled_qty":       float(o.filled_qty or 0),
                "filled_avg_price": round(float(o.filled_avg_price or 0), 4),
                "status":           o.status.value,
            }
            for o in orders
        ]
    except Exception as e:
        logger.warning(f"get_recent_orders: {e}")
        return []
