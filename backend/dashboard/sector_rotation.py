"""
板块轮动地图(RRG 风格)—— /challenge/lessons 页的动态四象限图数据。

对 15 个板块 ETF(含 ⚛️ 量子 QTUM)相对基准 SPY 计算:
  RS-Ratio    = 100 + z63(板块/SPY 价格比)        —— 横轴:相对强度
  RS-Momentum = 100 + z63(RS-Ratio 的 5 日变化)   —— 纵轴:相对动量
是对 JdK RS-Ratio/Momentum 的公开近似(原版口径私有),围绕 100 中心:
  右上=领涨(强且更强) 右下=转弱(强但衰减) 左下=落后 左上=转强(弱但回血)
轨迹 = 每 5 个交易日采样一点、取最近 8 点 —— 箭头方向就是资金轮动方向。

纯读数,随每日 publish 进 snapshot['sector_rotation'];不进 edge/决策 prompt。
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_BENCH = "SPY"
_SECTORS: list[tuple[str, str, str]] = [
    ("QTUM", "量子", "⚛️"),
    ("SMH",  "半导体", "🔩"),
    ("XLK",  "科技", "💻"),
    ("XLC",  "通讯", "📡"),
    ("XBI",  "生科", "🧬"),
    ("XLV",  "医疗", "🏥"),
    ("XLF",  "金融", "🏦"),
    ("XLE",  "能源", "🛢️"),
    ("XLI",  "工业", "🏭"),
    ("XLY",  "可选消费", "🛍️"),
    ("XLP",  "必需消费", "🛒"),
    ("XLU",  "公用事业", "⚡"),
    ("XLB",  "材料", "🧱"),
    ("XLRE", "地产", "🏠"),
    ("GDX",  "金矿", "⛏️"),
]
_Z_WIN = 63          # z 窗口(一个季度)
_MOM_LAG = 5         # 动量 = RS-Ratio 的 5 日变化
_STEP = 5            # 轨迹采样步长(≈周)
_TRAIL = 8           # 轨迹点数


def _quadrant(x: float, y: float) -> str:
    if x >= 100 and y >= 100:
        return "leading"
    if x >= 100:
        return "weakening"
    if y >= 100:
        return "improving"
    return "lagging"


def analyze_sector_rotation() -> dict | None:
    """15 板块 vs SPY 的 RRG 坐标 + 8 点轨迹;失败返回 None。"""
    try:
        import yfinance as yf
        tickers = [t for t, _, _ in _SECTORS] + [_BENCH]
        raw = yf.download(" ".join(tickers), period="1y", interval="1d",
                          progress=False, auto_adjust=True, group_by="ticker")
        spy = raw[_BENCH]["Close"].dropna()
        sectors = []
        as_of = str(pd.Timestamp(spy.index[-1]).date())
        for t, label, emoji in _SECTORS:
            try:
                c = raw[t]["Close"].dropna()
                if len(c) < _Z_WIN + _MOM_LAG + _STEP * _TRAIL:
                    continue
                ratio = (c / spy.reindex(c.index).ffill()).dropna()
                mu = ratio.rolling(_Z_WIN).mean()
                sd = ratio.rolling(_Z_WIN).std()
                rsr = 100 + (ratio - mu) / sd
                d = rsr.diff(_MOM_LAG)
                rsm = (100 + (d - d.rolling(_Z_WIN).mean()) / d.rolling(_Z_WIN).std())
                pts = []
                idx = list(range(len(ratio) - 1, -1, -_STEP))[:_TRAIL][::-1]
                for i in idx:
                    x, y = float(rsr.iloc[i]), float(rsm.iloc[i])
                    if pd.isna(x) or pd.isna(y):
                        continue
                    pts.append([round(x, 2), round(y, 2)])
                if len(pts) < 3:
                    continue
                hx, hy = pts[-1]
                sectors.append({
                    "ticker": t, "label": label, "emoji": emoji,
                    "trail": pts,
                    "x": hx, "y": hy,
                    "quadrant": _quadrant(hx, hy),
                    "ret20": round(float(c.iloc[-1] / c.iloc[-21] - 1), 4),
                })
            except Exception as e:
                logger.warning(f"sector_rotation: {t} failed — {e}")
        if len(sectors) < 6:
            return None
        return {
            "as_of": as_of,
            "benchmark": _BENCH,
            "sectors": sectors,
            "note": (f"RS=板块/SPY 价格比的 {_Z_WIN} 日 z(围绕100);动量=RS 的 "
                     f"{_MOM_LAG} 日变化再标准化;轨迹每 {_STEP} 个交易日采样、"
                     f"共 {_TRAIL} 点,箭头指向最新。JdK RRG 的公开近似,非官方口径。"),
        }
    except Exception as e:
        logger.warning(f"sector_rotation failed: {e}")
        return None
