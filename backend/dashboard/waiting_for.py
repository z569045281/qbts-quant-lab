"""「今天在等什么」— 把 HOLD 从黑箱变成看得懂的等待。

用户痛点(2026-07-22):"天天让我观望,我都不知道在等什么"。系统 HOLD 的真实
含义 = 六个回测验证过的一级扳机今天一个都没扣。这张卡把每个扳机的当前读数
和"离触发还差多少"摆出来 —— 纯展示,零新数据拉取(全部复用 snapshot 里
champs.today / relative_strength / btc_weekend / market_light 的现成读数),
不进 edge、不进决策权重,坏了也只是显示错。

扳机清单与阈值一一对应 decision.py _SYSTEM 的 B 级一级信号(mining.md 回测)。
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_RSI2_FIRE = 10.0     # RSI2<10 且 >200日线 → 后5天 +9.2%
_Z40_CHEAP = -1.5     # 对 IONQ 便宜 1.5σ → 配对买点(榜首策略)
_Z40_RICH  = 1.0      # 贵 1σ → 逆风清仓(反向警示)


def _rsi(series: pd.Series, n: int) -> float | None:
    """Wilder RSI, last value."""
    try:
        delta = series.diff()
        up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
        dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
        rs = up / dn
        v = float((100 - 100 / (1 + rs)).iloc[-1])
        return v if v == v else None
    except Exception:
        return None


def build_waiting_card(df_d: pd.DataFrame, snapshot: dict) -> dict | None:
    """六个一级扳机的当前读数 + 距触发距离。纯函数,失败返回 None。"""
    try:
        d = df_d.rename(columns=str.lower)
        close = float(d["close"].iloc[-1])
        today = (snapshot.get("champs") or {}).get("today") or {}
        rs = snapshot.get("relative_strength") or {}
        ml = snapshot.get("market_light") or {}
        bw = snapshot.get("btc_weekend")

        triggers: list[dict] = []

        # ① 特调抄底腿(招牌 +17.4% 是 2 年泡沫窗口的均值;全历史 n=55 中位 −0.3%、
        #    胜率 44%、姐妹 0/2 —— 第三十四轮。当加分项,别当单独进场理由)
        tj = today.get("tj_sig") or {}
        fast, slow = tj.get("fast"), tj.get("slow")
        fired = bool(tj.get("buy_base"))
        px = tj.get("buy_trigger_px")
        if fast is None:
            hint, reading = "读数缺失", "—"
        else:
            reading = f"快%R {fast:.0f} / 慢%R {slow:.0f}" if slow is not None else f"快%R {fast:.0f}"
            if fired:
                hint = "已触发(收盘确认口径)"
            elif fast < -80 and (slow is None or slow < -50):
                hint = (f"已在狙击区蹲守:收盘 ≥ ${px:.2f} 即上穿触发"
                        f"(第二十五轮:必须等收盘确认,勿盘中预挂)" if px else
                        "已在狙击区蹲守,等快%R上穿-80(收盘确认)")
            elif fast < -80:
                hint = f"快%R已超卖但慢%R {slow:.0f} 不够深(需<-50)"
            else:
                hint = f"快%R需先回落到-80下方再上穿(现{fast:.0f},差{fast + 80:.0f})"
        triggers.append({"key": "tiaojiu", "name": "特调抄底腿",
                         "record": "后5天+17.4% · 十轮最强",
                         "fired": fired, "reading": reading, "hint": hint})

        # ② RSI2<10 且 >200日线(后5天 +9.2%)
        rsi2 = _rsi(d["close"].astype(float), 2)
        ma200 = (float(d["close"].tail(200).mean())
                 if len(d) >= 200 else None)
        above = ma200 is not None and close > ma200
        fired = rsi2 is not None and rsi2 < _RSI2_FIRE and above
        if rsi2 is None:
            reading, hint = "—", "读数缺失"
        else:
            reading = (f"RSI2={rsi2:.0f},"
                       + (f"{'站上' if above else '低于'}200日线(${ma200:.2f})" if ma200 else "200日线数据不足"))
            if fired:
                hint = "已触发"
            elif rsi2 >= _RSI2_FIRE and not above:
                hint = f"双条件都差:RSI2 需 <10(差{rsi2 - _RSI2_FIRE:.0f}),且需收复200日线"
            elif rsi2 >= _RSI2_FIRE:
                hint = f"RSI2 需跌到 10 以下(现{rsi2:.0f})——大跌日回来看这条"
            else:
                hint = "RSI2 已超卖,但价格在200日线下方(下跌趋势中不接刀)"
        triggers.append({"key": "rsi2", "name": "RSI2 超卖回归",
                         "record": "后5天+9.2%",
                         "fired": bool(fired), "reading": reading, "hint": hint})

        # ③ 同行落后追赶(全系统最硬正腿:后5天 +11.7%)
        fired = bool(rs.get("catchup_triggered"))
        sis = rs.get("sisters_1d") or {}
        q1d = (rs.get("qbts_ret") or {}).get("1d")
        parts = [f"{k.upper()} {v * 100:+.1f}%" for k, v in sis.items() if v is not None]
        reading = (" / ".join(parts) + (f" vs QBTS {q1d * 100:+.1f}%" if q1d is not None else "")) or "—"
        hint = ("已触发" if fired else
                "需 IONQ+RGTI 单日均涨>3% 且 QBTS 落后 IONQ >1pp —— 同行暴涨日回来看这条")
        triggers.append({"key": "catchup", "name": "同行落后追赶",
                         "record": "后5天+11.7% · 最硬正腿",
                         "fired": fired, "reading": reading, "hint": hint})

        # ④ 周末BTC定周一(温和绿0~2%胜率71%;仅周一)
        if bw and bw.get("weekend_ret") is not None:
            ret = float(bw["weekend_ret"])
            fired = bool(bw.get("green"))
            reading = f"周末BTC {ret * 100:+.1f}%"
            hint = ("绿灯:日内单窗口(周一收盘前了结),温和绿最优" if fired
                    else "红周末 → 无信号(红周末做空已判死,别反着用)")
            triggers.append({"key": "btc_weekend", "name": "周末BTC定周一",
                             "record": "温和绿胜率71% · 仅周一",
                             "fired": fired, "reading": reading, "hint": hint})
        else:
            triggers.append({"key": "btc_weekend", "name": "周末BTC定周一",
                             "record": "温和绿胜率71% · 仅周一",
                             "fired": None, "reading": "非周一",
                             "hint": "只在周一开盘窗口生效,其余日子不适用"})

        # ⑤ 相对估值配对(便宜1.5σ=买点;贵1σ=逆风)
        z40 = today.get("z40")
        if z40 is None:
            fired, reading, hint = False, "—", "读数缺失"
        else:
            fired = z40 <= _Z40_CHEAP
            reading = f"对IONQ 40日z = {z40:+.2f}σ"
            if fired:
                hint = "已触发:QBTS 比 IONQ 便宜1.5σ,配对买点"
            elif z40 >= _Z40_RICH:
                hint = f"反向警示:比 IONQ 贵{z40:.1f}σ → 逆风,做多逻辑降档"
            else:
                hint = f"中性区,距便宜触发还差 {z40 - _Z40_CHEAP:.1f}σ"
        triggers.append({"key": "z40", "name": "相对估值配对",
                         "record": "榜首配对策略",
                         "fired": bool(fired), "reading": reading, "hint": hint})

        # ⑥ crypto/量子昨日顺风(t≈2.2-2.4;辅助腿,只加信心不独立开枪)
        btc_g, qtum_g = today.get("btc_green"), today.get("qtum_green")
        both_known = btc_g is not None or qtum_g is not None
        fired = bool(btc_g) or bool(qtum_g)
        reading = (f"BTC昨日{'🟢' if btc_g else '🔴'} / QTUM昨日{'🟢' if qtum_g else '🔴'}"
                   if both_known else "—")
        hint = ("顺风在(辅助腿:只给其他扳机加信心,不单独开枪)" if fired
                else "无顺风(注意:周中crypto跟单已判死,只有周一特权)")
        triggers.append({"key": "tailwind", "name": "crypto/量子顺风",
                         "record": "t≈2.2-2.4 · 辅助腿",
                         "fired": fired, "reading": reading, "hint": hint,
                         "aux": True})

        n_fired = sum(1 for t in triggers if t["fired"] and not t.get("aux"))
        return {
            "gate": {
                "regime": ml.get("regime"),
                "note": ml.get("note"),
            },
            "triggers": triggers,
            "n_fired": n_fired,
            "summary": (f"{n_fired} 个主扳机已触发" if n_fired
                        else "六个扳机均未触发 —— 今天观望就是在等上面任何一条变绿"),
        }
    except Exception as e:
        logger.warning(f"waiting_for card failed: {e}")
        return None
