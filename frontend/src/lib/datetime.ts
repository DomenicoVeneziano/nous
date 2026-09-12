// frontend/src/lib/datetime.ts

// "YYYY-MM-DD HH:MM:SS[.ffffff]" and its "T"-separated variant — a timestamp
// carrying no zone designator and no UTC offset.
const ZONELESS_RE = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$/;

/**
 * Parse a timestamp string as served by the API.
 *
 * The same field arrives in two shapes: offset-bearing ("…Z", "…+00:00") and
 * bare ("2026-07-27 12:00:00.123456"), depending on whether the value round-
 * tripped through SQLite. Everything stored is UTC either way, but `new Date()`
 * reads the bare shape as *local* time — so two assets written in the same
 * second can render hours apart. Bare values are pinned to UTC here; anything
 * that already carries an offset is passed through untouched.
 */
export function parseBackendDate(value: string): Date {
  return new Date(ZONELESS_RE.test(value) ? `${value.replace(' ', 'T')}Z` : value);
}

/**
 * Render a Date in the viewer's locale and zone.
 *
 * The input must already have come through parseBackendDate — this half of the
 * contract only formats, so no string ever reaches `new Date()` by another path.
 */
export function formatDateTime(d: Date): string {
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/**
 * Render a backend timestamp in the viewer's locale, or "Unknown" when unset.
 *
 * Deliberately not formatDateTime: the default locale rendering keeps the
 * seconds and the numeric date, which asset detail and history both rely on.
 * A missing value is genuinely unknown rather than zero, so it is not faked
 * from another field.
 */
export function formatTimestamp(value: string | null): string {
  if (!value) return 'Unknown';
  const parsed = parseBackendDate(value);
  if (Number.isNaN(parsed.getTime())) return 'Unknown';
  return parsed.toLocaleString();
}
