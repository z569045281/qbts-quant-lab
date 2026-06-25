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
