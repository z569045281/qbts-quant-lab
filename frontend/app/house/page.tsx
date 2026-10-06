"use client";

/* ─────────────────────────────────────────────────────────────────────────
   🏠 买房基金 · 人生财富积累(2026-10-06 新增,/house;定投专区 /dca 保留不动)
   用户:「推荐我各种让钱生钱的办法,我要真的能用,真钱会放进去,为了积累买房的钱」。

   页面只做三件事:
     ① 按你的情况算「买房到底要准备多少现金」(5% 首付计划 vs 20% 首付;维州印花税、首置补助)
     ② 算「钱放哪能长最快」(高息储蓄税后 vs 加上 FHSS 超级年金首置储蓄)
     ③ 列出能用的办法 + 不该碰的东西,每条带官方链接

   所有政策/利率数字都是 VERIFIED 当天查的(WebSearch,来源在页底),会变 —— 动钱前点链接再核一遍。
   不读后端:纯前端计算,输入只存在你这台浏览器(localStorage)。
   ───────────────────────────────────────────────────────────────────────── */

import { useEffect, useMemo, useState } from "react";

const VERIFIED = "2026-10-06";

// ── 当天核实的数字(改这里就行)───────────────────────────────────────────
const R = {
  rba: 0.046,          // RBA 现金利率,2026-09-29 加息到 4.60%
  hisa: 0.0525,        // 高息储蓄:无条件最高的持续利率(AMP GO Save)
  hisaCond: 0.0575,    // 有条件(每月存入/不取款)最高约 5.35–5.75%
  td12: 0.055,         // 12 个月定存约 5.40–5.60%
  fhssDeemed: 0.0751,  // FHSS 计息利率(ATO SIC 利率,2026-10 起这一季)
};
const CAP_5PCT = { melb: 950_000, regional: 650_000 };   // 5% 首付计划房价上限(维州)
const CONC_CAP = 32_500;     // 2026-27 税前供款上限(含雇主 12% SG)
const SG_RATE = 0.12;
const FHSS_YEAR = 15_000;    // FHSS 每财年上限
const FHSS_TOTAL = 50_000;   // FHSS 累计上限
const FHOG = 10_000;         // 维州首置补助:只限新房,≤$75 万
const FEES = 4_000;          // 律师/验房/贷款登记等杂费,粗估

// 2026-27 个税边际税率 + 2% Medicare(低收入的 Medicare 减免忽略)
function marginal(income: number): number {
  if (income <= 18_200) return 0;
  if (income <= 45_000) return 0.15 + 0.02;
  if (income <= 135_000) return 0.30 + 0.02;
  if (income <= 190_000) return 0.37 + 0.02;
  return 0.45 + 0.02;
}

// 维州印花税(普通税率)
function vicDuty(v: number): number {
  if (v <= 25_000) return v * 0.014;
  if (v <= 130_000) return 350 + (v - 25_000) * 0.024;
  if (v <= 960_000) return 2_870 + (v - 130_000) * 0.06;
  if (v <= 2_000_000) return v * 0.055;
  return 110_000 + (v - 2_000_000) * 0.065;
}
// 首置:≤$60 万全免;$60–75 万按比例打折(SRO 公式);>$75 万全额
function vicDutyFirstHome(v: number): number {
  if (v <= 600_000) return 0;
  if (v <= 750_000) return vicDuty(v) * (v - 600_000) / 150_000;
  return vicDuty(v);
}

type Inputs = {
  price: number; years: number; savings: number; monthly: number; income: number;
  firstHome: boolean; citizen: boolean; newBuild: boolean; melb: boolean;
};
const DEFAULTS: Inputs = {
  price: 650_000, years: 3, savings: 30_000, monthly: 2_000, income: 90_000,
  firstHome: true, citizen: true, newBuild: false, melb: true,
};
const KEY = "house-fund-inputs-v1";

const $ = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
const pct = (n: number, d = 2) => `${(n * 100).toFixed(d)}%`;

/** 逐月模拟:只用高息储蓄 vs 一部分走 FHSS。返回到期时可用于买房的钱。 */
function project(i: Inputs) {
  const t = marginal(i.income);
  const rAfter = R.hisa * (1 - t);                      // 储蓄利息要交税
  const months = Math.max(1, Math.round(i.years * 12));
  const room = Math.max(0, CONC_CAP - SG_RATE * i.income);   // 雇主供款之外还剩的税前额度
  const fhssYear = Math.min(FHSS_YEAR, room);

  // A:全部进高息储蓄
  let a = i.savings;
  for (let m = 0; m < months; m++) a = a * (1 + rAfter / 12) + i.monthly;

  // B:每年税前 fhssYear 走工资牺牲进 FHSS;它从到手工资里只扣 fhssYear×(1−t)
  let b = i.savings, sup = 0, sacrificed = 0;
  const monthlyNetCost = (fhssYear * (1 - t)) / 12;
  for (let m = 0; m < months; m++) {
    const pre = sacrificed < FHSS_TOTAL ? Math.min(fhssYear / 12, FHSS_TOTAL - sacrificed) : 0;
    const netCost = fhssYear > 0 ? (pre / (fhssYear / 12)) * monthlyNetCost : 0;
    sacrificed += pre;
    sup = sup * (1 + R.fhssDeemed / 12) + pre * 0.85;    // 进超级年金先交 15%
    b = b * (1 + rAfter / 12) + Math.max(0, i.monthly - netCost);
  }
  const releaseTax = Math.max(0, t - 0.30);              // 取出时按边际税率减 30% 抵扣
  const fhssNet = sup * (1 - releaseTax);
  return { t, rAfter, room, fhssYear, a, b: b + fhssNet, fhssNet, sacrificed, months };
}

function monthsToReach(i: Inputs, target: number, t: number): number | null {
  let bal = i.savings;
  const r = R.hisa * (1 - t);
  for (let m = 0; m <= 360; m++) {
    if (bal >= target) return m;
    bal = bal * (1 + r / 12) + i.monthly;
  }
  return null;
}

function Num({ label, value, onChange, step = 1000, prefix = "$" }: {
  label: string; value: number; onChange: (v: number) => void; step?: number; prefix?: string;
}) {
  return (
    <label className="block">
      <span className="text-meta text-ink-muted">{label}</span>
      <div className="mt-0.5 flex items-center rounded-inner border border-hairline bg-surface px-2">
        {prefix && <span className="text-body text-ink-faint">{prefix}</span>}
        <input type="number" inputMode="decimal" step={step} value={value}
          onChange={e => onChange(Number(e.target.value) || 0)}
          className="w-full bg-transparent px-1 py-1.5 text-card font-mono outline-none" />
      </div>
    </label>
  );
}

function Check({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-body text-gray-700">
      <input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function Method({ rank, title, worth, risk, liquid, who, how, link, linkLabel, children }: {
  rank: string; title: string; worth: string; risk: string; liquid: string; who: string;
  how: string[]; link: string; linkLabel: string; children?: React.ReactNode;
}) {
  return (
    <details className="group rounded-card border border-hairline bg-surface px-4 py-3">
      <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
        <div className="flex items-start gap-2">
          <span className="text-section leading-none">{rank}</span>
          <div className="min-w-0 flex-1">
            <div className="text-card font-semibold text-gray-900">{title}</div>
            <div className="mt-0.5 text-body text-emerald-700">{worth}</div>
            <div className="mt-1 flex flex-wrap gap-1.5 text-meta">
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">风险:{risk}</span>
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">取用:{liquid}</span>
            </div>
          </div>
          <span className="text-meta text-brand group-open:hidden">展开 ›</span>
        </div>
      </summary>
      <div className="mt-3 space-y-2 text-body text-gray-700">
        <div><span className="font-semibold">谁能用:</span>{who}</div>
        {children}
        <div>
          <div className="font-semibold">怎么做:</div>
          <ol className="ml-5 list-decimal space-y-0.5">{how.map((h, k) => <li key={k}>{h}</li>)}</ol>
        </div>
        <a href={link} target="_blank" rel="noreferrer" className="text-brand underline">{linkLabel} ↗</a>
      </div>
    </details>
  );
}

export default function HouseFundPage() {
  const [i, setI] = useState<Inputs>(DEFAULTS);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) setI({ ...DEFAULTS, ...JSON.parse(raw) });
    } catch { /* 隐私模式/禁用存储:用默认值 */ }
  }, []);
  const set = <K extends keyof Inputs>(k: K, v: Inputs[K]) => {
    setI(prev => {
      const next = { ...prev, [k]: v };
      try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* 忽略 */ }
      return next;
    });
  };

  const c = useMemo(() => {
    const p = project(i);
    const cap = i.melb ? CAP_5PCT.melb : CAP_5PCT.regional;
    const scheme5 = i.firstHome && i.citizen && i.price <= cap;
    const duty = i.firstHome && i.citizen ? vicDutyFirstHome(i.price) : vicDuty(i.price);
    const dutyFull = vicDuty(i.price);
    const grant = i.firstHome && i.citizen && i.newBuild && i.price <= 750_000 ? FHOG : 0;
    const need5 = 0.05 * i.price + duty + FEES - grant;
    const need20 = 0.20 * i.price + duty + FEES - grant;
    const lmi = [0.95 * i.price * 0.03, 0.95 * i.price * 0.04];   // 不用计划、贷 95% 时的房贷保险粗估
    return {
      ...p, cap, scheme5, duty, dutyFull, grant, need5, need20, lmi,
      m5: monthsToReach(i, need5, p.t), m20: monthsToReach(i, need20, p.t),
    };
  }, [i]);

  const fhssGain = c.b - c.a;
  const yearsLabel = `${i.years} 年后`;

  return (
    <main className="mx-auto max-w-[900px] space-y-5 px-4 py-5 sm:px-6 sm:py-6">
      <section className="rounded-card border border-hairline bg-surface px-5 py-4">
        <h1 className="text-section font-bold text-gray-900">🏠 买房基金 · 人生财富积累</h1>
        <p className="mt-1 text-body text-ink-muted">
          给「几年内要用的买房钱」排的办法清单,按你的情况现算。政策和利率核对于 {VERIFIED},
          会变 —— 动钱前点每条的官方链接再看一眼。一般性信息,不是个人理财建议。
        </p>
      </section>

      {/* ── 你的情况 ── */}
      <section className="rounded-card border border-hairline bg-surface px-5 py-4">
        <div className="mb-3 text-card font-semibold text-gray-800">① 你的情况(只存在这台浏览器)</div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Num label="想买的房价" value={i.price} step={10_000} onChange={v => set("price", v)} />
          <Num label="几年后买" value={i.years} step={0.5} prefix="" onChange={v => set("years", Math.max(0.5, v))} />
          <Num label="现在已有存款" value={i.savings} onChange={v => set("savings", v)} />
          <Num label="每月能存(到手后)" value={i.monthly} step={100} onChange={v => set("monthly", v)} />
          <Num label="年收入(税前)" value={i.income} step={5_000} onChange={v => set("income", v)} />
        </div>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
          <Check label="首次置业" value={i.firstHome} onChange={v => set("firstHome", v)} />
          <Check label="澳洲公民 / PR" value={i.citizen} onChange={v => set("citizen", v)} />
          <Check label="买新房(楼花/新建)" value={i.newBuild} onChange={v => set("newBuild", v)} />
          <Check label="墨尔本/吉朗(否=维州其他地区)" value={i.melb} onChange={v => set("melb", v)} />
        </div>
      </section>

      {/* ── 要准备多少现金 ── */}
      <section className="rounded-card border border-hairline bg-surface px-5 py-4">
        <div className="mb-3 text-card font-semibold text-gray-800">② 买 {$(i.price)} 的房,要准备多少现金</div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className={`rounded-inner border px-3 py-2.5 ${c.scheme5 ? "border-emerald-300 bg-emerald-50/50" : "border-hairline bg-gray-50"}`}>
            <div className="text-body font-semibold">走「5% 首付计划」(免房贷保险)</div>
            {c.scheme5 ? (
              <>
                <div className="mt-1 text-display font-bold font-mono">{$(c.need5)}</div>
                <div className="text-meta text-ink-muted">
                  首付 {$(0.05 * i.price)} + 印花税 {$(c.duty)} + 杂费约 {$(FEES)}{c.grant ? ` − 首置补助 ${$(c.grant)}` : ""}
                </div>
                <div className="mt-1 text-body">
                  按现在的存法:{c.m5 == null ? "30 年内存不够" : c.m5 === 0 ? "✅ 现在就够了" : `大约 ${c.m5} 个月后够(${(c.m5 / 12).toFixed(1)} 年)`}
                </div>
              </>
            ) : (
              <div className="mt-1 text-body text-ink-muted">
                不符合:要首次置业、公民/PR,且房价 ≤ {$(c.cap)}。
              </div>
            )}
          </div>
          <div className="rounded-inner border border-hairline bg-gray-50 px-3 py-2.5">
            <div className="text-body font-semibold">正常 20% 首付</div>
            <div className="mt-1 text-display font-bold font-mono">{$(c.need20)}</div>
            <div className="text-meta text-ink-muted">
              首付 {$(0.2 * i.price)} + 印花税 {$(c.duty)} + 杂费约 {$(FEES)}{c.grant ? ` − 首置补助 ${$(c.grant)}` : ""}
            </div>
            <div className="mt-1 text-body">
              按现在的存法:{c.m20 == null ? "30 年内存不够" : c.m20 === 0 ? "✅ 现在就够了" : `大约 ${c.m20} 个月后够(${(c.m20 / 12).toFixed(1)} 年)`}
            </div>
          </div>
        </div>
        <ul className="mt-3 list-disc space-y-0.5 pl-5 text-meta text-ink-muted">
          <li>印花税:{i.firstHome && i.citizen
            ? <>首置价 {$(c.duty)}(不享受首置的话是 {$(c.dutyFull)})。≤$60 万全免,$60–75 万按比例打折。</>
            : <>{$(c.dutyFull)}(没勾首置/公民,按普通税率)。</>}</li>
          <li>不走计划、只交 5% 首付的话,银行会收房贷保险,大约 {$(c.lmi[0])}–{$(c.lmi[1])} —— 这就是 5% 计划帮你省的钱。</li>
          <li>只是首付和交易成本;贷款批多少要看收入和银行,另算。</li>
        </ul>
      </section>

      {/* ── 钱放哪 ── */}
      <section className="rounded-card border border-hairline bg-surface px-5 py-4">
        <div className="mb-1 text-card font-semibold text-gray-800">③ 钱放哪长得最快({yearsLabel}能用的钱)</div>
        <p className="mb-3 text-meta text-ink-muted">
          你的边际税率 {pct(c.t, 0)}(含 2% Medicare)· 高息储蓄 {pct(R.hisa)} 税后只剩 {pct(c.rAfter)}
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-inner border border-hairline bg-gray-50 px-3 py-2.5">
            <div className="text-body font-semibold">全部放高息储蓄</div>
            <div className="mt-1 text-display font-bold font-mono">{$(c.a)}</div>
          </div>
          <div className={`rounded-inner border px-3 py-2.5 ${fhssGain > 500 ? "border-emerald-300 bg-emerald-50/50" : "border-hairline bg-gray-50"}`}>
            <div className="text-body font-semibold">储蓄 + FHSS(每年税前 {$(c.fhssYear)} 走超级年金)</div>
            <div className="mt-1 text-display font-bold font-mono">{$(c.b)}</div>
            <div className={`text-body ${fhssGain > 0 ? "text-emerald-700" : "text-down"}`}>
              {fhssGain > 0 ? `多出 ${$(fhssGain)}` : `少 ${$(-fhssGain)} —— 你的税率太低,FHSS 不划算`}
              <span className="text-meta text-ink-muted"> · 其中 FHSS 取出 {$(c.fhssNet)}</span>
            </div>
          </div>
        </div>
        {c.room < FHSS_YEAR && (
          <p className="mt-2 text-meta text-amber-700">
            ⚠️ 雇主 12% 供款已占掉大部分税前额度,你一年最多只能再放 {$(c.room)}(上限 {$(CONC_CAP)} 含雇主那部分)。
          </p>
        )}
        <p className="mt-2 text-meta text-ink-muted">
          算法:工资牺牲的钱进超级年金只交 15% 税,按 ATO 计息利率 {pct(R.fhssDeemed)} 计利息,
          取出时按你的税率减 30% 抵扣;不走 FHSS 的那部分照常到手存储蓄。粗算,实际以 ATO 出的金额为准。
        </p>
      </section>

      {/* ── 办法清单 ── */}
      <section className="space-y-2">
        <div className="px-1 text-card font-semibold text-gray-800">④ 能用的办法(按对你值多少排)</div>

        <Method rank="🥇" title="5% 首付计划(政府担保,免房贷保险)"
          worth={c.scheme5 ? `省房贷保险约 ${$(c.lmi[0])}–${$(c.lmi[1])},而且能早几年上车` : `你现在不符合(房价上限 ${$(c.cap)})`}
          risk="无(只是贷款更多,月供更高)" liquid="—"
          who={`首次置业(或 10 年没持有过房产)、澳洲公民/PR,房价 ≤ 墨尔本/吉朗 $95 万、维州其他 $65 万。2025-10-01 起取消收入上限和名额上限。`}
          how={["从官方名单里挑一家参与银行,或找贷款经纪代办", "拿到预批再看房,价格控制在上限内", "注意:贷 95% 月供高,先算自己扛不扛得住加息(RBA 今年已经加了 4 次)"]}
          link="https://firsthomebuyers.gov.au/australian-government-5-percent-deposit-scheme/5-percent-participating-lenders" linkLabel="官方:参与银行名单" />

        <Method rank="🥈" title="首置印花税减免 + 新房补助"
          worth={i.firstHome && i.citizen ? `印花税省 ${$(c.dutyFull - c.duty)}${c.grant ? `,外加补助 ${$(c.grant)}` : ""}` : "需要首置 + 公民/PR"}
          risk="无" liquid="交割时直接抵"
          who="维州首次置业、公民/PR、买来自住。≤$60 万免印花税,$60–75 万打折;买新房 ≤$75 万再给 $1 万补助(FHOG)。"
          how={["房价尽量压在 $60 万以内(免税)或 $75 万以内(打折 + 新房补助)", "签约后律师会帮你在交割时申请,不用自己跑", "通常要求买后 12 个月内入住、住满 12 个月"]}
          link="https://www.sro.vic.gov.au/buying-property/land-transfer-stamp-duty/concessions-exemptions-and-waivers/first-home-buyers/first-home-buyer-duty-exemption-or-concession" linkLabel="维州税务局 SRO" />

        <Method rank="🥉" title="FHSS 超级年金首置储蓄"
          worth={fhssGain > 0 ? `按你的情况 ${yearsLabel}多出约 ${$(fhssGain)}` : "你的税率下不划算"}
          risk="低(按 ATO 利率计息,不跟股市)" liquid="申请到账约 4–6 周,只能买首套房用"
          who={`首次置业。每年最多 ${$(FHSS_YEAR)}、累计 ${$(FHSS_TOTAL)};和雇主供款共用每年 ${$(CONC_CAP)} 的税前额度。税率越高越划算。`}
          how={["找 HR 设置工资牺牲(salary sacrifice),每月固定一笔进你的超级年金", "每笔都算 FHSS 合格供款,不用提前登记", "准备签约前,在 myGov → ATO 申请 FHSS 额度确认,再申请取出", "取出后 12 个月内要签约买房(可申请延期)"]}
          link="https://www.ato.gov.au/individuals-and-families/super-for-individuals-and-families/super/withdrawing-and-using-your-super/early-access-to-super/first-home-super-saver-scheme" linkLabel="ATO 官方页" />

        <Method rank="4️⃣" title={`高息储蓄账户(HISA)· 现在最高约 ${pct(R.hisa)} 无条件`}
          worth={`你每 $10,000 一年税后约多 ${$(10_000 * c.rAfter)}(四大行基础利率常常只有 0–1%)`}
          risk="无(每家银行 $25 万以内有政府担保)" liquid="随时取"
          who="所有人。首付的主力放这里。"
          how={[`选无条件的(约 ${pct(R.hisa)}),或能做到「每月存入一笔、当月不取」的选有条件的(约 5.35–${pct(R.hisaCond)})`, "新户常有 4 个月 6% 左右的优惠利率,优惠到期就换下一家", "同一家银行别超过 $25 万(政府担保上限)"]}
          link="https://www.canstar.com.au/savings-accounts/compare/best-savings-account-interest-rates/" linkLabel="Canstar 利率对比" />

        <Method rank="5️⃣" title={`12 个月定期存款 · 约 5.40–${pct(R.td12)}`}
          worth="利率锁死 12 个月,降息了也不受影响"
          risk="无(同样有 $25 万担保)" liquid="锁 12 个月,提前取要罚息"
          who="确定一年内不会用的那部分钱。"
          how={["RBA 今年已加息 4 次,市场预期 2027 年中开始降息 —— 现在锁一年等于锁在高点", "只放「确定一年后才用」的钱;首付交定金那笔留在储蓄账户", "到期前对比一下储蓄利率再决定续不续"]}
          link="https://www.canstar.com.au/term-deposits/compare/best-term-deposit-rates/" linkLabel="Canstar 定存对比" />

        <Method rank="6️⃣" title="Help to Buy 共享产权(2% 首付)"
          worth="首付只要 2%,政府出 30%(旧房)–40%(新房)占股"
          risk="中:以后房子涨了,政府那份也跟着涨" liquid="—"
          who="澳洲公民(PR 不行),年收入单人 ≤ $10 万 / 夫妻 ≤ $16 万,房价 ≤ 墨尔本 $95 万;每年 1 万个名额。"
          how={["只能通过参与的银行申请,不能直接找政府", "政府股份以后要按当时的房价买回,不是借款", "适合收入不高但想早上车的人;收入能存够 5% 的话,5% 计划更简单"]}
          link="https://firsthomebuyers.gov.au/australian-government-help-buy-scheme" linkLabel="firsthomebuyers.gov.au 官方页" />

        <Method rank="7️⃣" title="长期定投 ETF(5 年以上才用的钱)"
          worth="长期年化可能 7–9%,但短期可能跌 20–50%"
          risk="高:买房前一年碰上股灾,首付直接少一截" liquid="随时卖,但可能是亏着卖"
          who="离买房 5 年以上,或者不是买房钱的那部分。"
          how={["用澳洲上市的 ETF:VDHG / DHHF(一只全搞定),或 VAS + VGS 组合", "别用美国上市的 VTI/VOO:外国人持有超过 US$6 万有美国遗产税风险,还要填 W-8BEN", "每月固定买,别择时;离买房 2 年内逐步转成现金"]}
          link="https://moneysmart.gov.au/managed-funds-and-etfs/exchange-traded-funds-etfs" linkLabel="Moneysmart(ASIC)ETF 入门">
          <div className="rounded-inner bg-gray-50 px-2 py-1.5 text-meta text-gray-600">
            实测(yfinance):VDHG 持有 1 年亏钱概率 17%、最差 −14%;VAS 持有 2 年亏钱概率 9%、最差 −18%。
            ⚠️ 这些数据只覆盖 2014 年后的牛市,没包括 2008 年那种 −50% 的股灾 —— 真实风险比这大。
          </div>
        </Method>

        <Method rank="8️⃣" title="买房后:抵消账户(offset)"
          worth={`放在 offset 里的钱按房贷利率「赚」(约 6%+),而且不交税`}
          risk="无" liquid="随时取"
          who="有房贷之后。"
          how={["贷款时选带 offset 的浮动利率贷款", "工资和存款都放进 offset,每一块钱都在抵房贷利息", "对多数人,这比任何储蓄账户都划算(省的利息不用交税)"]}
          link="https://moneysmart.gov.au/home-loans/mortgage-offset-accounts" linkLabel="Moneysmart(ASIC)" />
      </section>

      {/* ── 不要做 ── */}
      <section className="rounded-card border border-red-200 bg-red-50/60 px-5 py-4">
        <div className="text-card font-semibold text-red-700">⛔ 买房钱不要碰的</div>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-body text-gray-700">
          <li><b>QBTS / QBTX / 任何杠杆 ETF / 加密币。</b>这套系统实测没有择时能力;QBTX 同期最大回撤 −95%。买房钱一分都不放进投机仓。</li>
          <li><b>投机仓总额 ≤ 总资产 10%</b> —— 而且「总资产」里先扣掉买房钱再算。</li>
          <li><b>离买房 2 年内还放在股票里。</b>股灾一来,不是少赚,是买不了。</li>
          <li><b>为了「多赚一点」锁长期定存或买理财产品</b> —— 首付要的是确定能用,不是最高收益。</li>
        </ul>
      </section>

      {/* ── 来源 ── */}
      <section className="rounded-card border border-hairline bg-surface px-5 py-4 text-meta text-ink-muted">
        <div className="mb-1 font-semibold text-gray-700">数据来源(核对于 {VERIFIED})</div>
        <ul className="list-disc space-y-0.5 pl-5">
          <li>RBA 2026-09-29 加息到 4.60%:<a className="underline" href="https://www.rba.gov.au/media-releases/2026/mr-26-27.html" target="_blank" rel="noreferrer">RBA</a></li>
          <li>储蓄 / 定存利率:<a className="underline" href="https://www.finder.com.au/savings-accounts/high-interest-savings-accounts" target="_blank" rel="noreferrer">Finder</a> · <a className="underline" href="https://www.canstar.com.au/term-deposits/compare/best-term-deposit-rates/" target="_blank" rel="noreferrer">Canstar</a></li>
          <li>5% 首付计划(2025-10-01 起无收入上限,墨尔本 $95 万):<a className="underline" href="https://integratedfinancegroup.com.au/blog/first-home-guarantee-2026-no-income-cap/" target="_blank" rel="noreferrer">Integrated Finance</a> · <a className="underline" href="https://www.mozo.com.au/home-loans/resources/guides/home-guarantee-scheme-guide" target="_blank" rel="noreferrer">Mozo</a></li>
          <li>FHSS 上限 $15k/$50k、ATO 计息利率 7.51%(2026-10 季):<a className="underline" href="https://www.ato.gov.au/tax-rates-and-codes/shortfall-interest-charge-rates" target="_blank" rel="noreferrer">ATO SIC 利率</a></li>
          <li>2026-27 税前供款上限 $32,500:<a className="underline" href="https://www.superguide.com.au/super-booster/concessional-super-contributions" target="_blank" rel="noreferrer">SuperGuide</a>;个税税率 15/30/37/45%:<a className="underline" href="https://www.wagecalculator.com.au/tax-rates/2026-27" target="_blank" rel="noreferrer">2026-27 税率</a></li>
          <li>维州印花税与首置减免:<a className="underline" href="https://sro.vic.gov.au/buying-property/land-transfer-stamp-duty/concessions-exemptions-and-waivers/first-home-buyers/first-home-buyer-duty-exemption-or-concession" target="_blank" rel="noreferrer">SRO</a>;FHOG $1 万:<a className="underline" href="https://nestpath.com.au/grants/vic" target="_blank" rel="noreferrer">NestPath</a></li>
          <li>Help to Buy:<a className="underline" href="https://firsthomebuyers.gov.au/australian-government-help-buy-scheme" target="_blank" rel="noreferrer">firsthomebuyers.gov.au</a></li>
        </ul>
      </section>
    </main>
  );
}
