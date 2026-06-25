// Backend timestamps are UTC. They may be tz-aware ("…+00:00"/"…Z") or, for older
// rows, naive (no suffix). A naive ISO string is parsed as *local* time by JS, which
// would mis-display the UTC instants the backend emits — so treat a tz-less string
// as UTC, then let the browser convert to the viewer's local zone.

export function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : iso + "Z");
  return isNaN(d.getTime()) ? null : d;
}

// "2026-06-25 16:09" in the viewer's local timezone (stable format, locale-agnostic).
export function fmtLocalDateTime(iso: string | null | undefined): string | null {
  const d = parseUtc(iso);
  if (!d) return null;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
         `${p(d.getHours())}:${p(d.getMinutes())}`;
}

// ── Melbourne (AEST/AEDT) annotations for the page's US-Eastern times ──────────
// We convert via IANA zones so US/AU daylight-saving is handled automatically.

const _MELB = "Australia/Melbourne";

// Offset (ms) of an IANA timezone from UTC at a given instant.
function _tzOffsetMs(timeZone: string, at: Date): number {
  const utc = new Date(at.toLocaleString("en-US", { timeZone: "UTC" }));
  const tz  = new Date(at.toLocaleString("en-US", { timeZone }));
  return tz.getTime() - utc.getTime();
}

// A US-Eastern wall clock (date "YYYY-MM-DD", time "HH:MM") → absolute instant.
function _etToDate(dateStr?: string | null, timeStr?: string | null): Date | null {
  if (!dateStr || !timeStr) return null;
  const d = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateStr);
  const t = /^(\d{1,2}):(\d{2})/.exec(timeStr);
  if (!d || !t) return null;
  const naive = new Date(Date.UTC(+d[1], +d[2] - 1, +d[3], +t[1], +t[2]));
  const at = new Date(naive.getTime() - _tzOffsetMs("America/New_York", naive));
  return isNaN(at.getTime()) ? null : at;
}

function _melbTime(at: Date | null): string | null {
  if (!at) return null;
  return at.toLocaleString("en-GB", { timeZone: _MELB,
    hour: "2-digit", minute: "2-digit", hour12: false });
}

function _melbMonthDay(at: Date | null): string | null {     // "MM-DD" in Melbourne
  if (!at) return null;
  return at.toLocaleDateString("en-CA", { timeZone: _MELB }).slice(5);
}

// " (墨 22:30)" suffix for a US-Eastern wall clock; adds MM-DD when it rolls to
// another Melbourne day (e.g. an afternoon-ET event landing the next AU morning).
export function etMelbSuffix(dateStr?: string | null, timeStr?: string | null): string {
  const at = _etToDate(dateStr, timeStr);
  const t = _melbTime(at);
  if (!t) return "";
  const d = _melbMonthDay(at);
  return d && dateStr && d !== dateStr.slice(5) ? ` (墨 ${d} ${t})` : ` (墨 ${t})`;
}

// "22:30" in Melbourne for an absolute epoch (seconds). Used for the live quote.
export function epochMelbTime(epochSec?: number | null): string | null {
  if (!epochSec) return null;
  return _melbTime(new Date(epochSec * 1000));
}
