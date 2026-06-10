"use client";

import { useMemo, useState } from "react";

interface PositionCalculatorProps {
  price:     number;
  atr:       number;            // absolute ATR in $
  verdict:   "BUY" | "SELL" | "HOLD";
  etfPrices: { qbtx: number | null; qbtz: number | null };
}

type Vehicle = "QBTS" | "QBTX" | "QBTZ";

const VEHICLES: { id: Vehicle; label: string; direction: "long" | "short"; leverage: number; desc: string }[] = [
  { id: "QBTS", label: "QBTS 现货",   direction: "long",  leverage: 1, desc: "标的本身，1×杠杆" },
  { id: "QBTX", label: "QBTX 2× 多",  direction: "long",  leverage: 2, desc: "Direxion 量子 2× 多头" },
  { id: "QBTZ", label: "QBTZ 2× 空",  direction: "short", leverage: 2, desc: "Direxion 量子 2× 空头" },
];

export function PositionCalculator({ price, atr, verdict, etfPrices }: PositionCalculatorProps) {
  const [capital, setCapital]   = useState(10000);
  const [riskPct, setRiskPct]   = useState(2);          // % of capital to risk per trade
  const [stopMult, setStopMult] = useState(1.5);        // ATR multiplier for stop distance
  const [rrRatio, setRrRatio]   = useState(2);          // target = entry +/- (rr * stop_distance)
  const [vehicle, setVehicle]   = useState<Vehicle>(
    verdict === "SELL" ? "QBTZ" : "QBTS"
  );

  const calc = useMemo(() => {
    const v = VEHICLES.find(x => x.id === vehicle)!;
    const direction = v.direction;
    const leverage  = v.leverage;

    // Stop distance in $ on the UNDERLYING (QBTS price)
    const underlyingStopDist = atr * stopMult;
    // For 2× ETFs, effective move per $ of QBTS movement is 2× as well (and so is loss)
    // → effective stop distance ON THE ETF = leverage × underlyingStopDist (approx)
    const effectiveStopDist = underlyingStopDist * leverage;

    // Risk in $ per share
    const maxRiskDollars = capital * (riskPct / 100);
    // Shares = max_risk / (effective stop distance per share at current price)
    // We use the ETF's own price as denominator scale; for simplicity assume ETF price ≈ tracks QBTS proportionally
    // For position sizing, the formula is: shares × stop_dist_per_share = max_risk
    const sharesFloat = maxRiskDollars / Math.max(effectiveStopDist, 0.01);
    const shares      = Math.max(0, Math.floor(sharesFloat));

    const positionValue = shares * price;

    // Entry / stop / target prices on the UNDERLYING (user thinks in QBTS terms)
    const entry = price;
    const stop  = direction === "long" ? price - underlyingStopDist : price + underlyingStopDist;
    const target= direction === "long" ? price + underlyingStopDist * rrRatio
                                        : price - underlyingStopDist * rrRatio;

    const maxLoss = Math.min(shares * effectiveStopDist, maxRiskDollars);
    const targetGain = shares * (underlyingStopDist * rrRatio) * leverage;

    // ── ETF price equivalents (approx 2× leverage, daily-reset model) ────
    // ETF_target = ETF_now × (1 + leverage × QBTS_pct_change × direction_sign)
    // For QBTX (2× bull): ETF moves WITH QBTS direction
    // For QBTZ (2× bear): ETF moves OPPOSITE QBTS direction
    const qbtsStopPct   = (stop   - price) / price;  // signed % move on QBTS to reach stop
    const qbtsTargetPct = (target - price) / price;  // signed % move on QBTS to reach target
    const qbtxNow = etfPrices.qbtx;
    const qbtzNow = etfPrices.qbtz;
    const qbtxStop   = qbtxNow != null ? qbtxNow * (1 + 2 * qbtsStopPct)   : null;
    const qbtxTarget = qbtxNow != null ? qbtxNow * (1 + 2 * qbtsTargetPct) : null;
    const qbtzStop   = qbtzNow != null ? qbtzNow * (1 - 2 * qbtsStopPct)   : null;
    const qbtzTarget = qbtzNow != null ? qbtzNow * (1 - 2 * qbtsTargetPct) : null;

    return {
      vehicleObj: v,
      direction, leverage,
      shares,
      positionValue,
      entry, stop, target,
      maxLoss, targetGain,
      rrRatio,
      underlyingStopDist,
      effectiveStopDist,
      qbtxNow, qbtxStop, qbtxTarget,
      qbtzNow, qbtzStop, qbtzTarget,
    };
  }, [capital, riskPct, stopMult, rrRatio, vehicle, price, atr, etfPrices]);

  const verdictAlignment =
    verdict === "BUY"  && calc.direction === "long"  ? { c: "text-emerald-600", t: "✓ 与今日综合判定一致" } :
    verdict === "SELL" && calc.direction === "short" ? { c: "text-emerald-600", t: "✓ 与今日综合判定一致" } :
    verdict === "HOLD"                                ? { c: "text-amber-600",  t: "⚠ 综合判定为观望" } :
                                                       { c: "text-[#F03A3E]", t: "✗ 方向与今日判定相反" };

  return (
    <section className="bg-white rounded-xl border border-[#EDEDF0] overflow-hidden">
      <div className="px-5 py-3.5 border-b border-[#EDEDF0] flex items-center justify-between">
        <span className="text-xs font-semibold text-[#525461] uppercase tracking-wider">
          🎯 仓位 & 止损计算器
        </span>
        <span className={`text-[11px] font-semibold ${verdictAlignment.c}`}>{verdictAlignment.t}</span>
      </div>

      <div className="px-5 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Left: Inputs */}
        <div className="space-y-3">
          <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">参数</div>

          <div>
            <label className="text-xs text-[#525461] block mb-1">总资金 ($)</label>
            <input type="number" value={capital} onChange={e => setCapital(Math.max(100, +e.target.value))}
                   className="w-full border border-[#EDEDF0] rounded-md px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[#006FFF]" />
          </div>

          <div>
            <label className="text-xs text-[#525461] block mb-1">每笔风险 ({riskPct}%)</label>
            <input type="range" min={0.5} max={5} step={0.5} value={riskPct}
                   onChange={e => setRiskPct(+e.target.value)} className="w-full" />
            <div className="text-[10px] text-gray-400 flex justify-between mt-0.5">
              <span>0.5%（保守）</span><span>5%（激进）</span>
            </div>
          </div>

          <div>
            <label className="text-xs text-[#525461] block mb-1">止损宽度 ({stopMult.toFixed(1)} × ATR = ${(atr * stopMult).toFixed(2)})</label>
            <input type="range" min={1} max={3} step={0.25} value={stopMult}
                   onChange={e => setStopMult(+e.target.value)} className="w-full" />
            <div className="text-[10px] text-gray-400 flex justify-between mt-0.5">
              <span>1.0×（紧）</span><span>3.0×（宽）</span>
            </div>
          </div>

          <div>
            <label className="text-xs text-[#525461] block mb-1">盈亏比 1 : {rrRatio.toFixed(1)}</label>
            <input type="range" min={1} max={5} step={0.5} value={rrRatio}
                   onChange={e => setRrRatio(+e.target.value)} className="w-full" />
            <div className="text-[10px] text-gray-400 flex justify-between mt-0.5">
              <span>1:1（保守）</span><span>1:5（激进）</span>
            </div>
          </div>

          <div>
            <label className="text-xs text-[#525461] block mb-1">交易标的</label>
            <div className="grid grid-cols-3 gap-1.5">
              {VEHICLES.map(v => (
                <button key={v.id} onClick={() => setVehicle(v.id)}
                        className={`px-2 py-2 text-xs font-medium rounded-md border transition-all
                          ${vehicle === v.id
                            ? "bg-[#006FFF] text-white border-[#006FFF]"
                            : "bg-white text-[#525461] border-[#EDEDF0] hover:border-[#006FFF]"}`}>
                  {v.label}
                </button>
              ))}
            </div>
            <div className="text-[10px] text-gray-400 mt-1">{calc.vehicleObj.desc}</div>
          </div>
        </div>

        {/* Right: Outputs */}
        <div className="bg-[#F6F6F8] rounded-lg p-4 space-y-2">
          <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">建议下单</div>

          <div className="flex justify-between items-baseline pb-2 border-b border-[#EDEDF0]">
            <span className="text-xs text-[#525461]">方向</span>
            <span className={`text-base font-bold ${calc.direction === "long" ? "text-emerald-600" : "text-[#F03A3E]"}`}>
              {calc.direction === "long" ? "↗ 做多" : "↘ 做空"} {calc.vehicleObj.label}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-[10px] text-gray-500 uppercase tracking-wider">买入数量</div>
              <div className="text-xl font-bold text-gray-900 font-mono">{calc.shares.toLocaleString()} 股</div>
              <div className="text-[10px] text-gray-400 mt-0.5">≈ ${calc.positionValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
            </div>
            <div>
              <div className="text-[10px] text-gray-500 uppercase tracking-wider">最大亏损</div>
              <div className="text-xl font-bold text-[#F03A3E] font-mono">-${calc.maxLoss.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              <div className="text-[10px] text-gray-400 mt-0.5">{((calc.maxLoss / capital) * 100).toFixed(2)}% 仓位</div>
            </div>
          </div>

          <div className="pt-2 border-t border-[#EDEDF0] space-y-1.5 text-xs">
            <div className="flex justify-between">
              <span className="text-[#525461]">入场（QBTS 现价）</span>
              <span className="font-mono font-semibold text-gray-900">${calc.entry.toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#525461]">止损价</span>
              <span className="font-mono font-semibold text-[#F03A3E]">${calc.stop.toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#525461]">目标价（{calc.rrRatio.toFixed(1)} R）</span>
              <span className="font-mono font-semibold text-emerald-600">${calc.target.toFixed(2)}</span>
            </div>
            <div className="flex justify-between pt-1 border-t border-[#EDEDF0]">
              <span className="text-[#525461]">达标盈利</span>
              <span className="font-mono font-bold text-emerald-600">+${calc.targetGain.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            </div>
          </div>

          {/* ── ETF price equivalents ── */}
          {(calc.qbtxNow != null || calc.qbtzNow != null) && (
            <div className="pt-3 mt-2 border-t border-[#EDEDF0]">
              <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                对应 ETF 价位（2× 杠杆近似）
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                {calc.qbtxNow != null && (
                  <div className="bg-emerald-50/50 border border-emerald-100 rounded px-2 py-1.5">
                    <div className="flex justify-between font-mono">
                      <span className="text-emerald-700 font-semibold">QBTX</span>
                      <span className="text-gray-500">现价 ${calc.qbtxNow.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between font-mono text-[10px] mt-0.5">
                      <span className="text-[#F03A3E]">止损 ${calc.qbtxStop?.toFixed(2)}</span>
                      <span className="text-emerald-600">目标 ${calc.qbtxTarget?.toFixed(2)}</span>
                    </div>
                  </div>
                )}
                {calc.qbtzNow != null && (
                  <div className="bg-red-50/50 border border-red-100 rounded px-2 py-1.5">
                    <div className="flex justify-between font-mono">
                      <span className="text-[#F03A3E] font-semibold">QBTZ</span>
                      <span className="text-gray-500">现价 ${calc.qbtzNow.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between font-mono text-[10px] mt-0.5">
                      <span className="text-[#F03A3E]">止损 ${calc.qbtzStop?.toFixed(2)}</span>
                      <span className="text-emerald-600">目标 ${calc.qbtzTarget?.toFixed(2)}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="text-[10px] text-gray-400 pt-2 leading-snug">
            注：2× ETF 持仓超过 3-5 天会有 vol decay 损耗，本计算未含。
            实际止损需放在 QBTS 价格上（不是 ETF 价格）。
          </div>
        </div>
      </div>
    </section>
  );
}
