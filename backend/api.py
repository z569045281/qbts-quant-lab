"""
FastAPI backend — connects data pipeline, AI factor generator, and backtest engine.
"""

import sys
import asyncio
import hashlib
import json
import math
import random
import re
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from data.fetcher import load_or_fetch
from data.sentiment import get_sentiment_context, get_fear_greed, sentiment_to_prompt_context
from data.enricher import enrich
from data.altdata import altdata_health_check, get_latest_etf_prices
from dashboard.strategies import run_all_strategies, aggregate_consensus
from dashboard.news       import get_news_snapshot
from dashboard.brief       import generate_brief, get_or_generate_brief, get_cached_brief
from dashboard.edge        import compute_edge
from dashboard.options     import get_options_signal
from dashboard.intraday    import get_intraday_signal
from dashboard.reddit      import fetch_reddit_signal
from dashboard.holdings    import get_holdings_signal
from dashboard.decision    import get_or_generate_decision, get_cached_decision
from dashboard.macro       import get_macro_calendar
from dashboard.calibration import log_prediction, grade_predictions, save_learned_weights
from factors.generator import generate_and_validate, generate_and_validate_ml
from factors.ml_factor import run_ml_walk_forward
from backtest.engine import (
    run_backtest, score_factor, split_data, is_overfit, run_walk_forward,
    walk_forward_splits, bars_per_month,
)
from backtest.metrics import factor_quality_summary
from backtest.ensemble import build_ensemble
from execution.trader import (
    is_configured, get_trading_client, get_data_client,
    get_account, get_position, get_recent_orders,
    compute_latest_signal, execute_signal as _execute_signal,
)

app = FastAPI(title="QBTS Factor Miner API")

app.add_middleware(
    CORSMiddleware,
    # Allow localhost + any private-LAN host on port 3000, so the app works
    # from other devices (iPad/phone) at e.g. http://192.168.1.109:3000.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistence
_LEADERBOARD_PATH = Path(__file__).parent / "data" / "leaderboard.json"
_FAVORITES_PATH   = Path(__file__).parent / "data" / "favorites.json"


def _load_favorites() -> set[str]:
    if not _FAVORITES_PATH.exists():
        return set()
    try:
        return set(json.loads(_FAVORITES_PATH.read_text()))
    except Exception:
        return set()


def _save_favorites(favs: set[str]) -> None:
    _FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FAVORITES_PATH.write_text(json.dumps(sorted(favs), indent=2))


favorites: set[str] = _load_favorites()


def _save_leaderboard() -> None:
    """Write leaderboard to disk, skipping non-serializable runtime fields."""
    _LEADERBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    saveable = [{k: v for k, v in e.items() if k not in ("signal",)} for e in leaderboard]
    _LEADERBOARD_PATH.write_text(json.dumps(saveable, cls=_Encoder, indent=2, ensure_ascii=False))


# ── HARD GATES (a factor must clear all of these) ────────────────────────────
# A factor on the leaderboard must be PROFITABLE — not just "directionally
# accurate". 52% hit rate with asymmetric returns can still lose money.
_MIN_N_SIGNALS   = 20         # statistical sample
_MIN_HIT_RATE    = 0.52       # directional edge above random
_MIN_OOS_TRADES  = 10         # tradeability
_MIN_OOS_SHARPE  = 0.30       # risk-adjusted return must be positive & meaningful
_MIN_OOS_RETURN  = -0.05      # tolerate up to -5% in case Sharpe positive but flat
_MAX_WORST_BAR_LOSS = -0.08   # gap-risk cap
_MAX_STOP_RATIO     = 0.40    # whipsaw filter

# ── SOFT THRESHOLDS (informational — used in score, NOT as hard gates) ───────
_IC_MEAN_TARGET  = 0.02
_ICIR_TARGET     = 0.25


def _ic_ok(entry: dict) -> bool:
    """Re-apply minimum quality gate to a stored leaderboard entry.

    Evict negative-Sharpe garbage on reload. Favorites are preserved
    UNCONDITIONALLY by _load_leaderboard regardless of this function.
    """
    ret    = entry.get("oos_total_return",  float("nan"))
    sharpe = entry.get("oos_sharpe_ratio",  float("nan"))
    return (
        math.isfinite(ret) and ret >= _MIN_OOS_RETURN
        and math.isfinite(sharpe) and sharpe >= _MIN_OOS_SHARPE
    )


def _load_leaderboard() -> list[dict]:
    if not _LEADERBOARD_PATH.exists():
        return []
    try:
        all_entries = json.loads(_LEADERBOARD_PATH.read_text())
        # Favorites are sacred — kept regardless of current gates.
        # Non-favorites are re-validated against the current quality bar.
        return [e for e in all_entries if e["id"] in favorites or _ic_ok(e)]
    except Exception:
        return []


# ─── Theme diversity enforcement ────────────────────────────────────────────
# Claude tends to converge on 1-2 dominant themes (e.g. "Volatility Regime").
# The dedup gate catches identical signals but not similar architectures.
# We classify each generated factor into one of 8 categories by keyword
# pattern, then ban any category that already has ≥ SATURATION factors,
# pushing Claude toward under-represented themes.

_THEME_KEYWORDS: dict[str, list[str]] = {
    "波动率体制 (volatility-regime)":
        [r"vol(?:atility)?[ -]regime", r"atr[ -]percentile", r"bb[ -]width",
         r"vol(?:atility)?[ -](?:texture|asymmetry|quantile)"],
    "散户拥挤 (retail-crowding)":
        [r"retail[ -]?(?:crowd|fomo|dip|sentiment)", r"etf[ -]?(?:flow|crowd|over)",
         r"overcrowd", r"qbtx|qbtz", r"leveraged[ -]etf"],
    "新闻催化 (news-catalyst)":
        [r"news[ -]?catalyst", r"\b8[ -]?k\b", r"earnings[ -](?:drift|ramp|vol)",
         r"post[ -]news", r"pre[ -]?earnings"],
    "同业相对 (peer-relative)":
        [r"peer[ -](?:div|lead|relative)", r"sector[ -](?:lead|peer)",
         r"\bionq\b|\brgti\b", r"quantum[ -]peer"],
    "微观结构 (microstructure)":
        [r"microstructure", r"gap[ -](?:fade|trap|vol)", r"volume[ -]climax",
         r"order[ -]flow", r"intraday[ -]range"],
    "均值回归 (mean-reversion)":
        [r"mean[ -]reversion", r"rsi[ -](?:extreme|reversion)",
         r"vwap[ -](?:extension|fade)", r"reversion[ -](?:distance|velocity)"],
    "动量延续 (momentum)":
        [r"momentum[ -](?:continuation|composite|persistence)",
         r"\bbreakout\b", r"multi[ -]timeframe[ -]momentum", r"52[ -]week",
         r"trend[ -]follow"],
    "情绪反向 (sentiment)":
        [r"fear[ -]dip", r"vix[ -]fear", r"sentiment[ -]bias", r"contrarian",
         r"fear[ -]?greed"],
}
_ALL_THEMES = list(_THEME_KEYWORDS.keys())
_SATURATION  = 3   # ban a theme once this many factors share it
_TARGET      = 2   # under this count = "preferred" theme


def classify_theme(name: str, description: str = "") -> str:
    text = f"{name} {description}".lower()
    for theme, patterns in _THEME_KEYWORDS.items():
        if any(re.search(p, text) for p in patterns):
            return theme
    return "其他 (other)"


def build_diversity_constraint(leaderboard: list[dict]) -> str:
    """
    Returns a prompt fragment listing saturated themes (forbidden) and
    under-represented themes (required). Empty string if leaderboard is too
    small for constraint to matter (<5 factors).
    """
    if len(leaderboard) < 5:
        return ""

    counts = Counter(classify_theme(e.get("name", ""), e.get("description", ""))
                     for e in leaderboard)
    saturated = [t for t in _ALL_THEMES if counts.get(t, 0) >= _SATURATION]
    under     = [t for t in _ALL_THEMES if counts.get(t, 0) < _TARGET]

    if not saturated:
        return ""   # nothing saturated yet — no constraint needed

    lines = [
        "--- ⛔ 主题饱和警告（HARD CONSTRAINT — 必须遵守） ---",
        "你绝对不能再生成以下主题的因子（排行榜已经被这些主题占满）：",
    ]
    for t in saturated:
        lines.append(f"  ❌ {t} — 已有 {counts[t]} 个，再写一个会被去重直接丢弃。")

    if under:
        lines.append("")
        lines.append("--- ✅ 必须从这些低代表性主题选一个 ---")
        for t in under:
            n = counts.get(t, 0)
            lines.append(f"  ✓ {t}（当前 {n}/{_TARGET}，急需补充）")

    lines.append("")
    lines.append("如果你写的因子被分类到 ⛔ 主题，回测耗时和 token 全部浪费。")
    lines.append("请明确在 docstring 第一行写出你选择的主题类别。")
    return "\n".join(lines)


# In-memory leaderboard — loaded from disk on startup
leaderboard: list[dict] = _load_leaderboard()


class _Encoder(json.JSONEncoder):
    """Handle numpy/pandas types that standard json can't serialize."""
    def default(self, obj):
        if isinstance(obj, pd.Series):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _sse(type_: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': type_, **kwargs}, cls=_Encoder)}\n\n"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/mining/stream")
async def mining_stream(rounds: int = 8):
    """SSE endpoint — auto-runs `rounds` full mining cycles and streams logs."""

    async def event_stream():
        yield _sse("log", level="info", msg="系统初始化，加载 QBTS 历史数据...")
        df_h, df_d = await asyncio.to_thread(load_or_fetch)

        # Refresh FINRA short-volume cache ONCE up front (incremental, ~5s).
        # enrich() below reads cache-only, so this is the only network fetch.
        from data.altdata import refresh_short_volume
        await asyncio.to_thread(refresh_short_volume)

        # Enrich full datasets — WFO applies factor to full history
        df_h_full = await asyncio.to_thread(enrich, df_h, "1h")
        df_d_full = await asyncio.to_thread(enrich, df_d, "1d")

        # Bar-count windows (replaces buggy calendar-day arithmetic)
        bpm_d, bpm_h = bars_per_month("1d"), bars_per_month("1h")
        D_IS, D_OOS, D_STEP = 6 * bpm_d, 1 * bpm_d, 1 * bpm_d
        H_IS, H_OOS, H_STEP = 6 * bpm_h, 1 * bpm_h, 1 * bpm_h

        # IS slice for Claude (last 12 trading months for context)
        df_d_is, _ = split_data(df_d_full, is_bars=12 * bpm_d, oos_bars=3 * bpm_d)
        df_h_is, _ = split_data(df_h_full, is_bars=12 * bpm_h, oos_bars=3 * bpm_h)

        # Count WFO windows for the log
        d_splits = walk_forward_splits(df_d_full, is_bars=D_IS, oos_bars=D_OOS, step_bars=D_STEP)
        h_splits = walk_forward_splits(df_h_full, is_bars=H_IS, oos_bars=H_OOS, step_bars=H_STEP)

        yield _sse("log", level="info",
                   msg=(
                       f"Walk-Forward 就绪 — "
                       f"日线 {len(df_d_full)}根 ({len(d_splits)} OOS窗口) | "
                       f"小时线 {len(df_h_full)}根 ({len(h_splits)} OOS窗口) | "
                       f"窗口配置 126/21/21 bar | 风控: 止损5% + vol-target2% | 特征列 {len(df_d_full.columns)} 个"
                   ))

        # EDGAR 8-K 状态诊断 — news_flag 全零说明 EDGAR 拉取失败，新闻类因子将无效
        news_flag_total = int(df_d_full["news_flag"].sum())
        days_min        = int(df_d_full["days_since_8k"].min())
        if news_flag_total == 0:
            yield _sse("log", level="error",
                       msg="⚠️ SEC EDGAR：0 条近期新闻标记 — EDGAR 拉取可能失败，news_flag 全为 0，"
                           "新闻类因子将生成全零信号，已自动过滤")
        else:
            yield _sse("log", level="info",
                       msg=f"SEC EDGAR：{news_flag_total} 条近期8-K标记 | 最近8-K距今 {days_min} 天")

        # 🆕 Phase-3a alt-data diagnostics
        alt_status = await asyncio.to_thread(altdata_health_check)
        alt_msgs = []
        for src, info in alt_status.items():
            label_src = {"etf": "ETF流", "earnings": "财报", "short": "做空"}.get(src, src)
            icon = "✓" if info["ok"] else "✗"
            alt_msgs.append(f"{icon} {label_src}({info['rows']})")
        any_failed = any(not v["ok"] for v in alt_status.values())
        yield _sse("log", level="error" if any_failed else "info",
                   msg=f"替代数据状态: {' | '.join(alt_msgs)}")

        # 抓实时情绪（一次性，整个 session 复用）
        yield _sse("log", level="info", msg="📡 正在抓取多维市场情绪数据...")
        sentiment_ctx, fear_greed = await asyncio.gather(
            asyncio.to_thread(get_sentiment_context),
            asyncio.to_thread(get_fear_greed),
        )
        sentiment_ctx["fear_greed"] = fear_greed
        sentiment_prompt = sentiment_to_prompt_context(sentiment_ctx)
        label_str = sentiment_ctx["sentiment_label"]
        bull_str  = f"{sentiment_ctx['bull_ratio']:.0%}"
        fg_str    = f"Fear&Greed={fear_greed['score']}({fear_greed['label']})" if fear_greed.get("available") else ""
        yield _sse("log", level="success" if label_str == "BULLISH" else "info",
                   msg=(
                       f"情绪快照 → StockTwits {label_str} (多头 {bull_str}, "
                       f"{sentiment_ctx['message_count']} 条) | {fg_str}"
                   ))
        yield _sse("sentiment", data=sentiment_ctx)

        yield _sse("log", level="info", msg=f"启动 {rounds} 轮全自动挖矿 🚀  (因子只能看 IS 数据，OOS 盲测打分)")

        # Track this-session failures so Claude can learn from them within the run
        session_failures: list[dict] = []
        # Cost telemetry — rough estimate, each generation attempt ≈ $0.017 with Sonnet 4.6
        _COST_PER_GEN = 0.017
        n_gen_attempts = 0   # incremented every time we call Claude for code generation

        for i in range(rounds):
            # 小时线 alpha 被成本拖累严重 (~55% 来回成本占用) — 降低权重到 1:10
            # 直到 Phase 3 加入更真实的 intraday cost 模型
            freq     = random.choices(["1d", "1h"], weights=[10, 1])[0]
            df_full  = df_h_full if freq == "1h" else df_d_full
            df_is    = df_h_is   if freq == "1h" else df_d_is
            n_splits = len(h_splits) if freq == "1h" else len(d_splits)
            label    = f"[{i+1}/{rounds}]"

            yield _sse("log", level="info",
                       msg=f"{label} 🤖 AI 生成因子... (freq={freq}, IS {len(df_is)}根, WFO {n_splits}个OOS窗口)")

            # ── Feedback context: leaderboard + recent failures ───────────────
            feedback_blocks: list[str] = []

            # Block A — already-passing factors (avoid duplicates)
            top_existing = sorted(leaderboard, key=lambda e: e.get("score", 0), reverse=True)[:6]
            if top_existing:
                lines = [
                    f"  - {e['name']} (hit={e.get('q_hit_rate', 0):.0%}, "
                    f"Sharpe={e.get('oos_sharpe_ratio', 0):.2f}, freq={e.get('freq', '?')})"
                    for e in top_existing
                ]
                feedback_blocks.append(
                    "--- ALREADY-DISCOVERED FACTORS (DO NOT DUPLICATE) ---\n"
                    + "\n".join(lines)
                )

            # Block B' — theme saturation constraint (hard ban + required themes)
            theme_block = build_diversity_constraint(leaderboard)
            if theme_block:
                feedback_blocks.append(theme_block)

            # Block B — this-session failures (learn from mistakes)
            if session_failures:
                recent_failures = session_failures[-8:]   # show last 8 failures
                lines = [
                    f"  ✗ {f['name'][:55]} → FAILED: {f['reason']}"
                    for f in recent_failures
                ]
                feedback_blocks.append(
                    "--- FACTORS THAT FAILED THIS SESSION (avoid these failure modes) ---\n"
                    + "\n".join(lines)
                )

            if feedback_blocks:
                feedback_ctx = (
                    "\n\n" + "\n\n".join(feedback_blocks)
                    + "\n\nDesign a STRUCTURALLY DIFFERENT factor. If many failures share a pattern "
                    "(e.g. all RSI-based factors fail), try a DIFFERENT signal source: "
                    "etf_long_share, short_pressure_z, days_to_earnings, peer divergence, "
                    "volume-climax, or news-driven (days_since_8k).\n"
                )
                round_prompt = sentiment_prompt + feedback_ctx
            else:
                round_prompt = sentiment_prompt

            # Mode selection: ML dominates (~26% historical pass rate vs rule's ~5%).
            # Keep a small rule allocation for diversity / sanity baseline only.
            mode = random.choices(["ml", "rule"], weights=[9, 1])[0]
            mode_label = "🧠 ML" if mode == "ml" else "📐 规则"

            try:
                if mode == "ml":
                    # ── ML mode: Claude writes feature engineering, system trains LightGBM ──
                    factor = await asyncio.to_thread(
                        generate_and_validate_ml, df_is, None, 2, round_prompt
                    )
                    n_gen_attempts += factor.get("_n_attempts", 1)
                    yield _sse("log", level="success",
                               msg=f"{label} ✅ {mode_label} 代码生成 → 「{factor['name']}」，训练 LightGBM…")

                    wf_res, oos_signal = await asyncio.to_thread(
                        run_ml_walk_forward, df_full, factor["code"], freq
                    )
                    # IS metrics: train a single model on the IS slice for reference
                    is_res, _ = await asyncio.to_thread(
                        run_ml_walk_forward, df_is, factor["code"], freq
                    )
                else:
                    # ── Rule mode: classic if-then factor ──
                    factor = await asyncio.to_thread(
                        generate_and_validate, df_is, None, 2, round_prompt
                    )
                    n_gen_attempts += factor.get("_n_attempts", 1)
                    yield _sse("log", level="success",
                               msg=f"{label} ✅ {mode_label} 代码生成 → 「{factor['name']}」，启动 Walk-Forward 回测…")

                    is_res = await asyncio.to_thread(run_backtest, df_is, factor["signal"], freq)
                    wf_res, oos_signal = await asyncio.to_thread(
                        run_walk_forward, df_full, factor["code"], freq
                    )

                # IC/ICIR — 在拼接 OOS 信号上计算（覆盖全部历史 OOS 区间）
                df_oos_aligned = df_full.reindex(oos_signal.index)
                quality = await asyncio.to_thread(
                    factor_quality_summary, oos_signal, df_oos_aligned, 1
                )

                # ── 质量门槛（精简后的硬关卡）──
                n_signals  = quality["n_signals"]
                hit_rate   = quality["hit_rate"]
                ic_mean    = quality["ic_mean"]
                icir       = quality["icir"]
                oos_ret    = wf_res.total_return
                n_trades   = wf_res.n_trades
                worst_bar  = wf_res.worst_bar_loss
                n_stops    = wf_res.n_stops
                stop_ratio = n_stops / max(n_trades, 1)

                fail_reason = None
                if n_signals < _MIN_N_SIGNALS:
                    fail_reason = f"激活信号{n_signals}条(需≥{_MIN_N_SIGNALS})，样本不足无法验证"
                elif not math.isfinite(hit_rate) or hit_rate < _MIN_HIT_RATE:
                    fail_reason = f"方向命中率{hit_rate:.1%}(需≥{_MIN_HIT_RATE:.0%})，无方向性优势"
                elif n_trades < _MIN_OOS_TRADES:
                    fail_reason = f"WFO交易次数{n_trades}(需≥{_MIN_OOS_TRADES})"
                elif wf_res.sharpe_ratio < _MIN_OOS_SHARPE:
                    fail_reason = (
                        f"WFO Sharpe={wf_res.sharpe_ratio:.2f}(需≥{_MIN_OOS_SHARPE})，"
                        f"风险调整后亏损（即使命中率达标也不赚钱）"
                    )
                elif not math.isfinite(oos_ret) or oos_ret < _MIN_OOS_RETURN:
                    fail_reason = f"OOS总收益{oos_ret:.1%}(需≥{_MIN_OOS_RETURN:.0%})"
                elif worst_bar < _MAX_WORST_BAR_LOSS:
                    fail_reason = f"单日最大亏损{worst_bar:.1%}(需≥{_MAX_WORST_BAR_LOSS:.0%})，存在跳空风险"
                elif stop_ratio > _MAX_STOP_RATIO:
                    fail_reason = f"止损率{stop_ratio:.0%}(需≤{_MAX_STOP_RATIO:.0%})，信号为噪音"

                if fail_reason:
                    session_failures.append({"name": factor["name"], "reason": fail_reason})
                    yield _sse("log", level="error",
                               msg=f"{label} 🚫 质量门槛未达标 → {fail_reason}，因子丢弃")
                    continue

                # Signal-hash dedup — Claude often regenerates near-identical
                # factors. Hash the stitched OOS signal pattern; if it matches an
                # existing entry, skip (the factor is effectively the same).
                sig_hash = hashlib.md5(
                    oos_signal.fillna(0).astype(int).values.tobytes()
                ).hexdigest()
                if any(e.get("sig_hash") == sig_hash for e in leaderboard):
                    session_failures.append({
                        "name": factor["name"],
                        "reason": "信号模式与现有因子完全重复（需要全新设计思路）",
                    })
                    yield _sse("log", level="info",
                               msg=f"{label} 🔁 信号模式与现有因子完全相同，跳过")
                    continue

                overfit   = is_overfit(is_res, wf_res)
                composite = score_factor(wf_res, quality)

                entry = {
                    "id":          str(uuid.uuid4()),
                    "name":        factor["name"],
                    "description": factor["description"],
                    "freq":        freq,
                    "code":        factor["code"],
                    "type":        mode,                     # "ml" or "rule"
                    "overfit":     overfit,
                    "wfo_n_splits": n_splits,
                    "sig_hash":    sig_hash,                 # dedup key
                    # IS metrics (most-recent IS window, for reference)
                    "is_win_rate":     is_res.win_rate,
                    "is_sharpe":       is_res.sharpe_ratio,
                    "is_max_drawdown": is_res.max_drawdown,
                    "is_total_return": is_res.total_return,
                    # WFO stitched OOS metrics (authoritative)
                    **{f"oos_{k}": v for k, v in wf_res.to_dict().items()},
                    # IC quality on stitched OOS
                    **{f"q_{k}": v for k, v in quality.items() if k != "ic_decay"},
                    "ic_decay":    quality["ic_decay"],
                    "score":       composite,
                    # stitched OOS signal — used for ensemble building
                    "signal":      oos_signal,
                }
                leaderboard.append(entry)
                leaderboard.sort(key=lambda x: x["score"], reverse=True)
                _save_leaderboard()

                public = {**{k: v for k, v in entry.items() if k not in ("code", "signal")}, "favorited": False}
                yield _sse("factor", factor=public)

                flag = "⚠️ 过拟合警告" if overfit else "✅ WFO 验证通过"
                yield _sse("log",
                           level="error" if overfit else "success",
                           msg=(
                               f"{label} {flag} | "
                               f"方向命中 {hit_rate:.1%} ({n_signals}信号) | "
                               f"WFO Sharpe {wf_res.sharpe_ratio:.2f} | "
                               f"IC={ic_mean:.3f} ICIR={icir:.2f} | "
                               f"止损 {n_stops}/{n_trades} | 最大单日亏 {worst_bar:.1%}"
                           ))

            except Exception as e:
                # On generation failure, conservatively assume max_retries (2) Claude calls happened
                n_gen_attempts += 2
                err_msg = str(e)[:200]
                session_failures.append({
                    "name": f"round {i+1} (generation)",
                    "reason": f"代码生成异常: {err_msg}",
                })
                yield _sse("log", level="error",
                           msg=f"{label} ❌ 失败: {err_msg}")

            await asyncio.sleep(0.3)

        passed = sum(1 for e in leaderboard if not e.get("overfit", True))

        # 自动构建组合：只用通过 OOS 验证的因子
        valid_records = [e for e in leaderboard if not e.get("overfit", True) and "signal" in e]
        ensemble_result = None
        ensemble_metrics = None
        if len(valid_records) >= 2:
            try:
                # Pass closes to enable risk-parity weighting (Phase 4 v2 ensemble)
                ensemble_result = build_ensemble(valid_records, closes=df_d_full["close"])
            except Exception:
                pass

        if ensemble_result and ensemble_result.signal is not None:
            # 组合因子回测：在 WFO 拼接 OOS 区间上跑（取信号覆盖的时间段）
            ens_idx = ensemble_result.signal.dropna().index
            df_ens_slice = df_d_full.reindex(ens_idx).dropna()
            ens_sig = ensemble_result.signal.reindex(df_ens_slice.index).fillna(0).astype(int)
            ens_bt  = run_backtest(df_ens_slice, ens_sig)
            ensemble_metrics = {
                "kept_count":   len(ensemble_result.kept_ids),
                "dropped_count": len(ensemble_result.dropped_ids),
                "kept_ids":     ensemble_result.kept_ids,
                **{f"ens_{k}": v for k, v in ens_bt.to_dict().items()},
            }
            yield _sse("ensemble", metrics=ensemble_metrics)
            yield _sse("log", level="success",
                       msg=(
                           f"🧩 组合因子构建完成 — "
                           f"纳入 {len(ensemble_result.kept_ids)} 个正交因子 | "
                           f"组合 OOS Sharpe {ens_bt.sharpe_ratio:.3f} | "
                           f"组合 OOS 胜率 {ens_bt.win_rate:.1%}"
                       ))

        est_cost = n_gen_attempts * _COST_PER_GEN
        yield _sse("log", level="info",
                   msg=(
                       f"💰 本次 session 共 {n_gen_attempts} 次 Claude 调用 ≈ "
                       f"${est_cost:.2f}（每轮均 ${est_cost/max(rounds,1):.3f}）"
                   ))
        yield _sse("done",
                   msg=f"✨ {rounds} 轮完成！{passed}/{len(leaderboard)} 个因子通过 WFO 验证。")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/admin/reset")
def admin_reset():
    """Clear non-favorited factors; preserved favorited entries survive reset."""
    kept = [e for e in leaderboard if e["id"] in favorites]
    cleared_count = len(leaderboard) - len(kept)
    leaderboard.clear()
    leaderboard.extend(kept)
    leaderboard.sort(key=lambda x: x["score"], reverse=True)
    if kept:
        _save_leaderboard()
    elif _LEADERBOARD_PATH.exists():
        _LEADERBOARD_PATH.unlink()
    return {"status": "ok", "cleared": cleared_count, "kept": len(kept)}


@app.get("/leaderboard")
def get_leaderboard():
    return [
        {**{k: v for k, v in e.items() if k not in ("code", "signal")}, "favorited": e["id"] in favorites}
        for e in leaderboard
    ]


@app.post("/factors/{factor_id}/favorite")
def toggle_favorite(factor_id: str):
    if not any(e["id"] == factor_id for e in leaderboard):
        raise HTTPException(status_code=404, detail="Factor not found")
    if factor_id in favorites:
        favorites.discard(factor_id)
        _save_favorites(favorites)
        return {"favorited": False}
    else:
        favorites.add(factor_id)
        _save_favorites(favorites)
        return {"favorited": True}


@app.get("/factors/{factor_id}/code")
def get_factor_code(factor_id: str):
    for e in leaderboard:
        if e["id"] == factor_id:
            return {"id": factor_id, "code": e["code"]}
    raise HTTPException(status_code=404, detail="Factor not found")


@app.get("/factors/{factor_id}/chart")
async def get_factor_chart(factor_id: str):
    """Return OHLCV + buy/sell signal markers for charting."""
    entry = next((e for e in leaderboard if e["id"] == factor_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Factor not found")

    code = entry.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="No code stored for this factor")

    freq = entry.get("freq", "1d")
    df_h, df_d = await asyncio.to_thread(load_or_fetch)
    df = df_h if freq == "1h" else df_d

    # Remove duplicate timestamps and ensure ascending order
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = enrich(df, freq=freq)

    if entry.get("type") == "ml":
        # ML factor: re-run WFO to reconstruct the OOS signal series
        _, signal = await asyncio.to_thread(run_ml_walk_forward, df, code, freq)
        # Reindex to full df (bars outside OOS get 0)
        signal = signal.reindex(df.index, fill_value=0)
    else:
        # Rule factor: simply execute compute_factor
        ns: dict = {"pd": pd, "np": np}
        exec(compile(code, "<factor>", "exec"), ns)
        signal = ns["compute_factor"](df.copy())

    ohlcv = [
        {
            "time": int(ts.timestamp()),
            "open":  round(float(row["open"]),  4),
            "high":  round(float(row["high"]),  4),
            "low":   round(float(row["low"]),   4),
            "close": round(float(row["close"]), 4),
        }
        for ts, row in df.iterrows()
    ]

    # Transition-based markers: show entry AND exit points
    # signal=1 in response → buy/cover arrow; signal=-1 → sell/short arrow
    vals = signal.values.astype(int)
    markers = []
    prev = 0
    for ts, val in zip(signal.index, vals):
        if val != prev:
            if val == 1:
                markers.append({"time": int(ts.timestamp()), "signal": 1})
            elif val == -1:
                markers.append({"time": int(ts.timestamp()), "signal": -1})
            elif prev == 1:   # exit long → sell
                markers.append({"time": int(ts.timestamp()), "signal": -1})
            elif prev == -1:  # cover short → buy
                markers.append({"time": int(ts.timestamp()), "signal": 1})
        prev = val

    oos_start  = df.index[-1] - timedelta(days=3 * 30)
    split_time = int(oos_start.timestamp())

    return {
        "factor_name": entry["name"],
        "freq":        freq,
        "ohlcv":       ohlcv,
        "markers":     markers,
        "split_time":  split_time,
    }


# ── Today's signals — Phase 4 live trading panel ──────────────────────────

_TODAY_CACHE: dict = {"ts": 0.0, "payload": None}
_TODAY_CACHE_TTL = 600   # 10 minutes


def _compute_latest_signal(entry: dict, df: pd.DataFrame, df_full: pd.DataFrame) -> dict:
    """
    Return the most-recent signal value for a single factor.
    Handles both rule and ML types. df is the latest-bar-aligned enriched frame.
    """
    code = entry["code"]
    f_type = entry.get("type", "rule")

    if f_type == "ml":
        # Re-train on the most recent IS window, predict on the last bar
        _, signal_series = run_ml_walk_forward(df_full, code, entry.get("freq", "1d"))
        # Reindex to df (signal_series covers WFO OOS bars only); last bar may
        # not be in the OOS window — fall back to a fresh single-window prediction.
        if len(signal_series) and signal_series.index[-1] == df.index[-1]:
            latest = int(signal_series.iloc[-1])
        else:
            latest = 0   # outside WFO coverage — neutral
    else:
        ns: dict = {"pd": pd, "np": np}
        exec(compile(code, "<factor>", "exec"), ns)
        sig = ns["compute_factor"](df.copy())
        latest = int(sig.iloc[-1]) if not sig.empty else 0

    return {
        "id":          entry["id"],
        "name":        entry["name"],
        "type":        f_type,
        "freq":        entry.get("freq", "1d"),
        "score":       entry.get("score", 0.0),
        "oos_sharpe":  entry.get("oos_sharpe_ratio", 0.0),
        "hit_rate":    entry.get("q_hit_rate", 0.0),
        "signal":      latest,           # -1 / 0 / +1
        "label":       {1: "BUY", -1: "SELL", 0: "HOLD"}[latest],
    }


@app.get("/today/signals")
async def today_signals(top_n: int = 6):
    """
    Live aggregate view: what does each top-N factor say for the LATEST bar?
    Includes risk-parity weighted ensemble consensus.
    Cached for ~10 minutes since QBTS data updates daily / hourly.
    """
    import time
    now = time.time()
    if _TODAY_CACHE["payload"] and (now - _TODAY_CACHE["ts"] < _TODAY_CACHE_TTL):
        return _TODAY_CACHE["payload"]

    if not leaderboard:
        return {"factors": [], "ensemble": None, "as_of": None, "reason": "leaderboard empty"}

    # Use top-N by score (score now bakes in CI-lower Sharpe → trust)
    top = sorted(leaderboard, key=lambda e: e.get("score", 0), reverse=True)[:top_n]

    df_h, df_d = await asyncio.to_thread(load_or_fetch)
    df_d_enr   = await asyncio.to_thread(enrich, df_d, "1d")
    df_h_enr   = await asyncio.to_thread(enrich, df_h, "1h")

    # Per-factor latest signal
    per_factor: list[dict] = []
    for e in top:
        df_full = df_h_enr if e.get("freq") == "1h" else df_d_enr
        try:
            info = await asyncio.to_thread(_compute_latest_signal, e, df_full, df_full)
            per_factor.append(info)
        except Exception as ex:
            per_factor.append({
                "id":     e["id"],
                "name":   e["name"],
                "type":   e.get("type", "rule"),
                "signal": 0,
                "label":  "ERROR",
                "error":  str(ex)[:120],
            })

    # Ensemble consensus: risk-parity weighted vote among factors that returned a signal
    active = [f for f in per_factor if "error" not in f]
    if active:
        # Build a synthetic factor-records list for build_ensemble using just the latest bar
        # For simplicity here we compute weighted sum directly.
        weights_raw = {f["id"]: max(f["oos_sharpe"], 0) + 0.1 for f in active}
        total_w = sum(weights_raw.values()) or 1.0
        weights = {fid: w / total_w for fid, w in weights_raw.items()}
        blend   = sum(weights[f["id"]] * f["signal"] for f in active)
        if blend >  0.20:
            ens_label, ens_dir = "BUY",  1
        elif blend < -0.20:
            ens_label, ens_dir = "SELL", -1
        else:
            ens_label, ens_dir = "HOLD", 0
        # Annotate per-factor weights
        for f in per_factor:
            f["weight"] = round(weights.get(f["id"], 0.0), 3)
        ensemble = {
            "signal":     ens_dir,
            "label":      ens_label,
            "raw_blend":  round(float(blend), 4),
            "n_active":   len(active),
            "n_buy":      sum(1 for f in active if f["signal"] == 1),
            "n_sell":     sum(1 for f in active if f["signal"] == -1),
            "n_hold":     sum(1 for f in active if f["signal"] == 0),
        }
    else:
        ensemble = None

    payload = {
        "as_of":    df_d.index[-1].isoformat(),
        "close":    round(float(df_d["close"].iloc[-1]), 2),
        "factors":  per_factor,
        "ensemble": ensemble,
    }
    _TODAY_CACHE["payload"] = payload
    _TODAY_CACHE["ts"]      = now
    return payload


# ── Dashboard endpoint — classic strategies + news ───────────────────────

_DASHBOARD_CACHE: dict = {"ts": 0.0, "payload": None}
_DASHBOARD_CACHE_TTL = 600   # 10 minutes


@app.get("/dashboard/snapshot")
async def dashboard_snapshot(force_refresh: bool = False):
    """
    Aggregated decision dashboard.
      - 8 empirically validated classic strategies (Connors, Bernard & Thomas, etc.)
      - QBTS + peer news with Claude impact analysis
      - Overall consensus combining both
    Cached for 10 minutes.
    """
    import time
    now = time.time()
    if not force_refresh and _DASHBOARD_CACHE["payload"] and (now - _DASHBOARD_CACHE["ts"] < _DASHBOARD_CACHE_TTL):
        return _DASHBOARD_CACHE["payload"]

    # 1. Latest QBTS data
    _, df_d = await asyncio.to_thread(load_or_fetch)
    df = await asyncio.to_thread(enrich, df_d, "1d")

    last_close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    today_pct  = (last_close / prev_close - 1) if prev_close > 0 else 0.0

    # 2. Run all classic strategies
    strategies = await asyncio.to_thread(run_all_strategies, df)
    strat_consensus = aggregate_consensus(strategies)

    # 3. Fetch + analyze news
    try:
        news_snap = await asyncio.to_thread(get_news_snapshot, force_refresh)
    except Exception as e:
        news_snap = {"as_of": None, "items": [], "aggregate": {"label": "neutral", "signal": 0,
                     "score": 0, "n_bull": 0, "n_bear": 0, "n_neutral": 0, "n_items": 0},
                     "error": str(e)[:120]}

    # 4. Combined verdict
    strat_w = 2          # strategies carry more weight (data-driven)
    news_w  = 1          # news is a soft tilt (sentiment / context)
    total_score = strat_consensus["raw_score"] * strat_w + news_snap["aggregate"]["score"] * news_w
    if total_score >= 4:
        verdict_signal, verdict_label = 1,  "BUY"
    elif total_score <= -4:
        verdict_signal, verdict_label = -1, "SELL"
    else:
        verdict_signal, verdict_label = 0,  "HOLD"

    # 5. 60-day chart data + key technical levels
    chart_df = df.tail(60).copy()
    sma20    = df["close"].rolling(20).mean()
    sma200   = df["close"].rolling(200, min_periods=50).mean()
    high_52w = float(df["close"].tail(252).max())
    low_52w  = float(df["close"].tail(252).min())

    candles = []
    for ts, row in chart_df.iterrows():
        candles.append({
            "time":  int(ts.timestamp()),
            "open":  round(float(row["open"]),  2),
            "high":  round(float(row["high"]),  2),
            "low":   round(float(row["low"]),   2),
            "close": round(float(row["close"]), 2),
        })
    sma20_line = [
        {"time": int(ts.timestamp()), "value": round(float(v), 2)}
        for ts, v in sma20.tail(60).items() if pd.notna(v)
    ]
    sma200_line = [
        {"time": int(ts.timestamp()), "value": round(float(v), 2)}
        for ts, v in sma200.tail(60).items() if pd.notna(v)
    ]
    chart_data = {
        "candles":     candles,
        "sma20":       sma20_line,
        "sma200":      sma200_line,
        "high_52w":    round(high_52w, 2),
        "low_52w":     round(low_52w, 2),
        "atr_14":      round(float(df["atr_14"].iloc[-1]) * last_close, 2),  # absolute ATR
    }

    # 5.5 — Live ETF prices (used by brief + position calculator)
    etf_prices = await asyncio.to_thread(get_latest_etf_prices)

    payload = {
        "as_of":           df.index[-1].isoformat(),
        "price":           round(last_close, 2),
        "today_change":    round(today_pct, 4),
        "strategies":      strategies,
        "strategy_consensus": strat_consensus,
        "news":            news_snap,
        "verdict": {
            "signal":  verdict_signal,
            "label":   verdict_label,
            "score":   total_score,
            "weights": {"strategies": strat_w, "news": news_w},
        },
        "chart":           chart_data,
        "etf_prices":      etf_prices,            # {qbtx: float | None, qbtz: float | None}
        # Brief is loaded from persistent cache — never auto-regenerated here.
        # Use POST /dashboard/brief/refresh to force a fresh one (costs ~$0.015).
        "brief":               None,
        "brief_generated_at":  None,
    }

    cached_brief, cached_at = get_cached_brief()
    payload["brief"]              = cached_brief
    payload["brief_generated_at"] = cached_at

    # ── AI Decision (the user-facing verdict) — cached only here. ──
    # publish.py / POST /dashboard/decision/refresh force-generate it.
    cached_dec, dec_at = get_cached_decision()
    payload["decision"]              = cached_dec
    payload["decision_generated_at"] = dec_at

    # ── Pull options + intraday + reddit signals (all cached internally) ────
    try:
        opt_sig = await asyncio.to_thread(get_options_signal)
    except Exception:
        opt_sig = None
    try:
        intr_sig = await asyncio.to_thread(get_intraday_signal)
    except Exception:
        intr_sig = None
    try:
        reddit_sig = await asyncio.to_thread(fetch_reddit_signal)
    except Exception:
        reddit_sig = None
    try:
        holdings_sig = await asyncio.to_thread(get_holdings_signal)
    except Exception:
        holdings_sig = None
    try:
        macro_cal = await asyncio.to_thread(get_macro_calendar)
    except Exception:
        macro_cal = None
    payload["options"]  = opt_sig
    payload["intraday"] = intr_sig
    payload["reddit"]   = reddit_sig
    payload["holdings"] = holdings_sig
    payload["macro"]    = macro_cal

    # ── Source status map: tells the UI which signals are active/inactive/error
    # so the user knows when something needs setup (e.g. Reddit OAuth missing). ─
    def _src_status(sig: dict | None) -> dict:
        if not sig:
            return {"status": "error", "label": "拉取失败"}
        if sig.get("signal", 0) != 0:
            return {"status": "active",   "label": sig.get("label", ""),
                    "rationale": sig.get("rationale", "")}
        # signal == 0 → HOLD; check why (no data vs neutral reading)
        reason = sig.get("rationale", "")
        if "OAuth" in reason or "缺失" in reason or "失败" in reason or "需要" in reason:
            return {"status": "needs_setup", "label": "未配置",
                    "rationale": reason}
        return {"status": "neutral",   "label": "中性",
                "rationale": reason}

    payload["sources_status"] = {
        "options":  _src_status(opt_sig),
        "intraday": _src_status(intr_sig),
        "reddit":   _src_status(reddit_sig),
        "holdings": _src_status(holdings_sig),
    }

    # ── Meta-model edge: combines all signal sources with learned weights ───
    today_cached = _TODAY_CACHE.get("payload") if (
        _TODAY_CACHE.get("payload") and (now - _TODAY_CACHE.get("ts", 0) < _TODAY_CACHE_TTL)
    ) else None
    try:
        payload["edge"] = compute_edge(
            payload, today_cached, opt_sig, intr_sig, reddit_sig, holdings_sig,
        )
    except Exception as e:
        payload["edge"] = {"signal": 0, "label": "HOLD", "error": str(e)[:100]}

    # ── Auto-log this prediction for future calibration (idempotent per day) ─
    try:
        log_prediction(payload["price"], payload["as_of"], payload["edge"])
    except Exception:
        pass

    _DASHBOARD_CACHE["payload"] = payload
    _DASHBOARD_CACHE["ts"]      = now
    return payload


@app.post("/dashboard/brief/refresh")
async def refresh_brief():
    """
    Force-regenerate the AI brief. This is the ONLY entry point that calls
    Claude for the brief — costs ~$0.015 per call.
    """
    snap = await dashboard_snapshot(force_refresh=False)
    brief, generated_at, _ = await asyncio.to_thread(get_or_generate_brief, snap, True)

    # Update in-memory snapshot cache so subsequent /dashboard/snapshot returns
    # the fresh brief without regenerating the whole payload.
    if _DASHBOARD_CACHE["payload"]:
        _DASHBOARD_CACHE["payload"]["brief"]              = brief
        _DASHBOARD_CACHE["payload"]["brief_generated_at"] = generated_at

    return {"brief": brief, "generated_at": generated_at}


@app.post("/dashboard/decision/refresh")
async def refresh_decision():
    """
    Force-regenerate the AI trade decision (~$0.05 Claude call).
    Pulls mined-factor signals + earnings calendar as extra context.
    """
    snap = await dashboard_snapshot(force_refresh=False)

    extras: dict = {}
    try:
        from data.altdata import fetch_earnings_dates
        dates = await asyncio.to_thread(fetch_earnings_dates)
        extras["earnings_dates"] = [d.strftime("%Y-%m-%d") for d in dates]
    except Exception:
        pass
    try:
        today = await today_signals(top_n=5)
        extras["mined_factors"] = today.get("factors", [])
    except Exception:
        pass
    try:
        _, df_d = await asyncio.to_thread(load_or_fetch)
        extras["calibration"] = await asyncio.to_thread(grade_predictions, df_d)
    except Exception:
        pass

    decision, gen_at, fresh = await asyncio.to_thread(
        get_or_generate_decision, snap, True, extras
    )
    if _DASHBOARD_CACHE["payload"]:
        _DASHBOARD_CACHE["payload"]["decision"]              = decision
        _DASHBOARD_CACHE["payload"]["decision_generated_at"] = gen_at
    return {"decision": decision, "generated_at": gen_at, "fresh": fresh}


@app.get("/dashboard/calibration")
async def dashboard_calibration():
    """
    Grade all logged predictions against realized 5-bar forward returns.
    Persists the per-source weight multipliers so edge.py auto-uses them next time.
    """
    _, df_d = await asyncio.to_thread(load_or_fetch)
    result = await asyncio.to_thread(grade_predictions, df_d)
    try:
        save_learned_weights(result)
    except Exception:
        pass
    return result


# ── Trading endpoints ──────────────────────────────────────────────────────

@app.get("/trading/status")
async def trading_status():
    """Account snapshot + current QBTS position + best factor signal."""
    if not is_configured():
        return {"configured": False,
                "hint": "在 .env 中填写 ALPACA_API_KEY 和 ALPACA_SECRET_KEY"}

    tc = get_trading_client()
    dc = get_data_client()

    account  = get_account(tc).to_dict()
    position = get_position(tc)

    # Best non-overfit factor
    best = next((e for e in leaderboard if not e.get("overfit", True) and e.get("code")),
                next((e for e in leaderboard if e.get("code")), None))

    signal = None
    if best:
        df_h, df_d = await asyncio.to_thread(load_or_fetch)
        freq_best = best.get("freq", "1d")
        df        = df_h if freq_best == "1h" else df_d
        df        = await asyncio.to_thread(enrich, df, freq_best)
        signal    = compute_latest_signal(best, df)

    orders = await asyncio.to_thread(get_recent_orders, tc)

    return {
        "configured": True,
        "account":    account,
        "position":   position.to_dict() if position else None,
        "signal":     signal,
        "orders":     orders,
    }


@app.get("/trading/execute")
async def trading_execute():
    """SSE: compute signal → decide → submit order → stream progress."""

    async def stream():
        if not is_configured():
            yield _sse("log", level="error",
                       msg="❌ Alpaca API 未配置，请在 .env 中填写 ALPACA_API_KEY / ALPACA_SECRET_KEY")
            yield _sse("done", success=False)
            return

        yield _sse("log", level="info", msg="🔗 连接 Alpaca Paper Trading 账户...")
        tc = get_trading_client()
        dc = get_data_client()

        account  = await asyncio.to_thread(get_account, tc)
        position = await asyncio.to_thread(get_position, tc)

        yield _sse("account", data=account.to_dict())
        yield _sse("log", level="info",
                   msg=(f"账户资产 ${account.portfolio_value:,.2f} | "
                        f"可用现金 ${account.cash:,.2f} | "
                        f"今日 P&L {account.daily_pnl:+.2f} ({account.daily_pnl_pct:+.2f}%)"))

        if position:
            yield _sse("log", level="info",
                       msg=(f"当前持仓: 多 {position.qty:.0f} 股 @ ${position.avg_entry_price} | "
                            f"浮盈 {position.unrealized_pl:+.2f} ({position.unrealized_plpc:+.2f}%)"))
        else:
            yield _sse("log", level="info", msg="当前持仓: 空仓")

        # Pick best factor
        best = next((e for e in leaderboard if not e.get("overfit", True) and e.get("code")),
                    next((e for e in leaderboard if e.get("code")), None))

        if not best:
            yield _sse("log", level="error", msg="❌ 排行榜为空，请先挖矿生成因子")
            yield _sse("done", success=False)
            return

        yield _sse("log", level="info",
                   msg=f"📊 使用因子: 「{best['name']}」(OOS评分 {best.get('score', 0):.3f})")

        # Compute signal on fresh data
        yield _sse("log", level="info", msg="📡 拉取最新 QBTS 行情...")
        df_h, df_d = await asyncio.to_thread(load_or_fetch, force_refresh=True)
        freq_best  = best.get("freq", "1d")
        df         = df_h if freq_best == "1h" else df_d
        df         = await asyncio.to_thread(enrich, df, freq_best)
        signal     = compute_latest_signal(best, df)

        label_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(signal["label"], "")
        yield _sse("signal", data=signal)
        yield _sse("log", level="success" if signal["label"] == "BUY" else "info",
                   msg=f"{label_emoji} 信号: {signal['label']}  (原始值={signal['value']})")

        # Execute
        yield _sse("log", level="info", msg="⚡ 提交委托...")
        results = await asyncio.to_thread(_execute_signal, tc, dc, signal["value"])

        for r in results:
            level = "success" if r["action"] in ("buy", "sell") else "info"
            yield _sse("log", level=level, msg=r["msg"])
            if r["action"] in ("buy", "sell"):
                yield _sse("order", data=r)

        # Refresh state
        await asyncio.sleep(1.5)
        account2  = await asyncio.to_thread(get_account, tc)
        position2 = await asyncio.to_thread(get_position, tc)
        orders2   = await asyncio.to_thread(get_recent_orders, tc)
        yield _sse("refresh", account=account2.to_dict(),
                   position=position2.to_dict() if position2 else None,
                   orders=orders2)
        yield _sse("done", success=True,
                   msg=f"执行完成 — 账户资产 ${account2.portfolio_value:,.2f}")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
