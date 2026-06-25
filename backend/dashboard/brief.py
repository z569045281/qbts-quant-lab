"""
AI Daily Brief — synthesises the dashboard's structured data into a
3-4 sentence executive summary the user reads first.

Input  : full snapshot (strategies + news + verdict)
Output : 3-4 sentences of Chinese commentary that names specific drivers,
         calls out conflicts, and ends with a concrete action recommendation.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

_BRIEF_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "daily_brief.json"
_BRIEF_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

_SYSTEM = """你是一名资深量化交易员，正在给客户写当日 QBTS（D-Wave Quantum）的早盘简报。

客户实际通过两个杠杆 ETF 交易：
  - QBTX：2× 多头 ETF（看多 QBTS 时买入）
  - QBTZ：2× 空头 ETF（看空 QBTS 时买入，绝大多数情况比直接做空 QBTS 简单）

输入会包含：
  - 当前 QBTS 价格、当日涨跌
  - QBTX、QBTZ 当前价格（用于把 QBTS 目标价换算成 ETF 入场/止损/目标价）
  - 8 个学术策略的信号（多/空/观望 + 置信度 + 简要理由）
  - 最近 11 条新闻的 AI 解读（情绪、冲击力、关键词）
  - 综合判定（BUY/SELL/HOLD）

ETF 价格换算规则（2× 杠杆 + 日内重置近似）：
  - QBTS 涨 X% → QBTX 涨约 2X%, QBTZ 跌约 2X%
  - QBTS 跌 X% → QBTX 跌约 2X%, QBTZ 涨约 2X%
  - 即 ETF_target = ETF_now × (1 + 2 × QBTS_pct_change)
  - 例：QBTS $29 → $32（+10.3%），QBTX $4.50 → 约 $4.50 × 1.207 = $5.43；QBTZ $8.00 → 约 $8.00 × 0.794 = $6.35

输出要求（严格遵守）：
  - 全部中文，3 到 4 句话
  - 句式必须包含具体数字和具体策略名称
  - 第 1 句：今天的核心矛盾或主导信号
  - 第 2 句：关键证据（最强支持 + 最强反对）
  - 第 3 句：主要风险
  - 第 4 句：具体行动建议——**必须分别给出 QBTS 触发价 + QBTX 或 QBTZ 的对应入场/止损/目标价**
    - 看多用 QBTX，看空用 QBTZ
    - 数字必须按上面的换算规则计算
    - 如果 HOLD 给出"QBTS 突破 $X / 跌破 $Y 时分别该买 QBTX / QBTZ 的具体触发"
  - 不要用模糊词如「可能」「也许」「建议谨慎」
  - 不要写免责声明、不要写「仅供参考」
  - 直接输出正文，不要标题或编号

风格示范（假设 QBTS $29.40，QBTX $4.50，QBTZ $8.00）：
「QBTS 今日 $29.40 暴涨 14.2%，触发挤空模型高置信买入信号但同时撞上新闻过反应卖出信号——5日做空率 59%、量比 3.9 倍是真实的挤空燃料，而 RSI 70 + 8-K 后单日 +14% 又是经典的衰竭信号。最大风险是这种『散户押注做空爆仓后的最后一波』，进去就是接最后一棒。当前盘整等待方向：QBTS 若放量突破 $30.5（+3.7%）则买 QBTX 入场约 $4.83、止损 $4.50、目标 $5.43（对应 QBTS $32+）；若高开缩量跌破 $27.5（-6.5%）则买 QBTZ 入场约 $9.04、止损 $8.46、目标 $9.92（对应 QBTS $26-27）。」"""


def generate_brief(snapshot: dict) -> str:
    """
    Build the user message from snapshot, call Claude, return the brief text.
    Caller is responsible for caching (the snapshot endpoint itself caches).
    """
    strats         = snapshot.get("strategies", [])
    consensus      = snapshot.get("strategy_consensus", {})
    news           = snapshot.get("news", {})
    verdict        = snapshot.get("verdict", {})
    price          = snapshot.get("price", 0)
    today_chg      = snapshot.get("today_change", 0)

    # Compact strategy block
    strat_lines = []
    for s in strats:
        if s["signal"] != 0 or s["confidence"] != "low":
            strat_lines.append(
                f"  • {s['name']} → {s['label']} ({s['confidence']}): {s['rationale']}"
            )

    # Most material news (high impact + non-neutral, or top 3)
    news_items = news.get("items", [])
    material = [n for n in news_items
                if n.get("ai", {}).get("impact") in ("high", "medium")
                and n.get("ai", {}).get("sentiment") != "neutral"]
    if len(material) < 3:
        material = news_items[:5]
    news_lines = [
        f"  • [{n['ai']['sentiment']}/{n['ai']['impact']}] {n['title']} → {n['ai']['reasoning']}"
        for n in material[:6]
    ]

    etf = snapshot.get("etf_prices", {}) or {}
    qbtx_p = etf.get("qbtx")
    qbtz_p = etf.get("qbtz")
    etf_line = (
        f"QBTX 现价: ${qbtx_p}    QBTZ 现价: ${qbtz_p}    "
        f"(换算: ETF变化 ≈ 2 × QBTS变化%；QBTX=做多QBTS的载体，QBTZ=做空QBTS的载体)"
        if (qbtx_p is not None or qbtz_p is not None)
        else "QBTX/QBTZ 价格数据不可用 — 仅给出 QBTS 价位"
    )

    user_msg = (
        f"QBTS 现价: ${price}    今日 {today_chg*100:+.2f}%\n"
        f"{etf_line}\n"
        f"综合判定: {verdict.get('label')} (分数 {verdict.get('score')})\n"
        f"策略票数: ▲{consensus.get('n_buy',0)} ●{consensus.get('n_hold',0)} ▼{consensus.get('n_sell',0)} "
        f"(加权 {consensus.get('raw_score',0)})\n\n"
        f"策略详情：\n" + ("\n".join(strat_lines) or "  (无活跃信号)") + "\n\n"
        f"重大新闻 ({len(material)} 条):\n" + ("\n".join(news_lines) or "  (无重大新闻)") + "\n\n"
        f"请按系统提示的格式输出 3-4 句话简报，并在第 4 句给出 QBTS 触发价 + 对应的 QBTX/QBTZ 入场/止损/目标价。"
    )

    try:
        resp = _CLIENT.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Brief generation failed: {e}")
        return f"⚠️ 简报生成失败：{str(e)[:80]}。请刷新或检查 API 配置。"


def get_or_generate_brief(snapshot: dict, force_refresh: bool = False) -> tuple[str, str, bool]:
    """
    Persistent brief cache — only regenerates when force_refresh=True OR no cache exists.

    Returns:
        (brief_text, generated_at_iso, was_freshly_generated)
    """
    if not force_refresh and _BRIEF_CACHE_PATH.exists():
        try:
            cached = json.loads(_BRIEF_CACHE_PATH.read_text())
            return cached["brief"], cached["generated_at"], False
        except Exception as e:
            logger.warning(f"Brief cache read failed ({e}), regenerating…")

    brief = generate_brief(snapshot)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")   # tz-aware UTC → 前端转本地
    try:
        _BRIEF_CACHE_PATH.write_text(
            json.dumps({"brief": brief, "generated_at": now_iso}, ensure_ascii=False)
        )
    except Exception as e:
        logger.warning(f"Brief cache write failed: {e}")
    return brief, now_iso, True


def get_cached_brief() -> tuple[str | None, str | None]:
    """Return (brief_text, generated_at_iso) without regenerating. None if no cache."""
    if not _BRIEF_CACHE_PATH.exists():
        return None, None
    try:
        cached = json.loads(_BRIEF_CACHE_PATH.read_text())
        return cached["brief"], cached["generated_at"]
    except Exception:
        return None, None
