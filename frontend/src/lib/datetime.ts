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
