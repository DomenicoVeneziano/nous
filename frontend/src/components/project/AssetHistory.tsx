// frontend/src/components/project/AssetHistory.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { AssetChange, AssetChangeField } from '../../types/assetChange';
import { fetchAssetChanges } from '../../api/assets';
import { parseBackendDate } from '../../lib/datetime';
import TagChip from '../shared/TagChip';

interface Props {
  projectId: string;
  assetId: string;
}

const PAGE = 50;

const FIELD_LABEL: Record<AssetChangeField, string> = {
  status_code:    'Status Code',
  title:          'Title',
  redirects_to:   'Redirects To',
  content_length: 'Content Length',
  technologies:   'Technologies',
  dns_records:    'DNS Records',
};

/** The two fields whose value columns hold a delta (removed / added) rather
 *  than a before / after pair. */
const SET_FIELDS: AssetChangeField[] = ['technologies', 'dns_records'];

/** Same scale as the detail panel's status colouring, so a recorded 301 reads
 *  the same here as it does in the asset's current state. */
function statusColor(value: string | null): string {
  const code = value === null ? NaN : Number(value);
  if (!code || Number.isNaN(code)) return 'var(--text-muted)';
  if (code >= 200 && code < 300) return 'var(--status-success)';
  if (code >= 300 && code < 400) return 'var(--status-info)';
  if (code >= 400 && code < 500) return 'var(--status-warning)';
  return 'var(--status-error)';
}

/** Render an ISO timestamp in the viewer's locale, or "Unknown" when unset. */
function formatTimestamp(value: string | null): string {
  if (!value) return 'Unknown';
  const parsed = parseBackendDate(value);
  if (Number.isNaN(parsed.getTime())) return 'Unknown';
  return parsed.toLocaleString();
}

/** Read one side of a set-valued delta. The column is written by the engine but
 *  read here defensively — a malformed or truncated payload degrades to an
 *  empty list rather than tearing down the panel. */
function parseEntries(value: string | null): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((e): e is string => typeof e === 'string');
  } catch {
    return [];
  }
}

interface ChangeGroup {
  key: string;
  changed_at: string;
  changes: AssetChange[];
}

/**
 * Fold the flat list into one entry per scan, preserving the server's ordering.
 *
 * Changes written outside a scan carry no `scan_id`, so they group by timestamp
 * instead. A single pass over the list keeps the groups in the order they were
 * served — object key iteration order is not a sort, and re-sorting client-side
 * would fight the cursor the next page is drawn against.
 */
function groupChanges(items: AssetChange[]): ChangeGroup[] {
  const groups: ChangeGroup[] = [];
  const index = new Map<string, number>();
  for (const item of items) {
    const key = item.scan_id ?? `at:${item.changed_at}`;
    const at = index.get(key);
    if (at === undefined) {
      index.set(key, groups.length);
      groups.push({ key, changed_at: item.changed_at, changes: [item] });
    } else {
      groups[at].changes.push(item);
    }
  }
  return groups;
}

const labelStyle: React.CSSProperties = {
  fontSize: 10, fontWeight: 600, color: 'var(--text-muted)',
  textTransform: 'uppercase', letterSpacing: '0.08em',
};

const fieldStyle: React.CSSProperties = {
  fontSize: 11, color: 'var(--text-muted)', width: 106, flexShrink: 0,
};

/** One `+`/`−` prefixed entry of a set-valued delta. */
function DeltaChip({ entry, added }: { entry: string; added: boolean }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
      <span style={{
        color: added ? 'var(--status-success)' : 'var(--status-error)',
        fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, lineHeight: 1,
      }}>
        {added ? '+' : '−'}
      </span>
      <TagChip label={entry} variant={added ? 'user' : 'system'} />
    </span>
  );
}

function ScalarValue({ field, value }: { field: AssetChangeField; value: string | null }) {
  if (value === null || value === '') {
    return <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>N/A</span>;
  }
  return (
    <span style={{ color: field === 'status_code' ? statusColor(value) : 'var(--text-primary)' }}>
      {value}
    </span>
  );
}

function ChangeRow({ change }: { change: AssetChange }) {
  const isSet = SET_FIELDS.includes(change.field);
  const removed = isSet ? parseEntries(change.old_value) : [];
  const added   = isSet ? parseEntries(change.new_value) : [];

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <div style={fieldStyle}>{FIELD_LABEL[change.field] ?? change.field}</div>
      {isSet ? (
        added.length === 0 && removed.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>None</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, flex: 1 }}>
            {added.map((e) => <DeltaChip key={`+${e}`} entry={e} added />)}
            {removed.map((e) => <DeltaChip key={`-${e}`} entry={e} added={false} />)}
          </div>
        )
      ) : (
        <div style={{
          flex: 1, fontSize: 11, fontFamily: 'var(--font-mono)',
          display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
          wordBreak: 'break-all',
        }}>
          <ScalarValue field={change.field} value={change.old_value} />
          <span style={{ color: 'var(--text-muted)' }}>→</span>
          <ScalarValue field={change.field} value={change.new_value} />
        </div>
      )}
    </div>
  );
}

export default function AssetHistory({ projectId, assetId }: Props) {
  const [changes, setChanges] = useState<AssetChange[]>([]);
  const [cursor, setCursor]   = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');

  // The detail panel is reused as the operator moves between assets, so every
  // request is tagged with the asset it was issued for: a page that lands after
  // the selection moved on is dropped rather than appended to the new asset's
  // history.
  const loadedFor = useRef(assetId);

  useEffect(() => {
    loadedFor.current = assetId;
    setChanges([]);
    setCursor(null);
    setError('');
    setLoading(true);
    fetchAssetChanges(projectId, assetId, undefined, PAGE)
      .then((page) => {
        if (loadedFor.current !== assetId) return;
        setChanges(page.items);
        setCursor(page.next_cursor);
        setLoading(false);
      })
      .catch(() => {
        if (loadedFor.current !== assetId) return;
        setError('Failed to load history');
        setLoading(false);
      });
  }, [projectId, assetId]);

  // Paging only ever moves forward from the cursor the last page returned, so
  // page one is never refetched and the list terminates when the server stops
  // handing one back.
  const loadMore = () => {
    if (!cursor || loading) return;
    const forAsset = assetId;
    setLoading(true);
    setError('');
    fetchAssetChanges(projectId, assetId, cursor, PAGE)
      .then((page) => {
        if (loadedFor.current !== forAsset) return;
        setChanges((prev) => [...prev, ...page.items]);
        setCursor(page.next_cursor);
        setLoading(false);
      })
      .catch(() => {
        if (loadedFor.current !== forAsset) return;
        setError('Failed to load history');
        setLoading(false);
      });
  };

  const groups = useMemo(() => groupChanges(changes), [changes]);

  return (
    <div>
      <div style={{ ...labelStyle, marginBottom: 12 }}>
        History
      </div>

      {error && (
        <div style={{
          background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)',
          borderRadius: 'var(--radius-md)', padding: '5px 10px', fontSize: 11,
          color: 'var(--status-error)', fontFamily: 'var(--font-mono)', marginBottom: 10,
        }}>{error}</div>
      )}

      {groups.length === 0 ? (
        // Only the first page can land on an empty list, so this doubles as the
        // first-load indicator: paging in more rows leaves the list populated
        // and takes the branch below, keeping the rows already on screen.
        loading ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading…</div>
        ) : !error && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No recorded changes</div>
        )
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {groups.map((g) => (
            <div
              key={g.key}
              style={{
                background: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)', padding: '10px 12px',
                display: 'flex', flexDirection: 'column', gap: 8,
              }}
            >
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)',
              }}>
                {formatTimestamp(g.changed_at)}
              </div>
              {g.changes.map((c) => <ChangeRow key={c.id} change={c} />)}
            </div>
          ))}
        </div>
      )}

      {cursor && (
        <button
          onClick={loadMore}
          disabled={loading}
          style={{
            marginTop: 8, background: 'transparent', border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
            padding: '4px 10px', fontSize: 11,
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.6 : 1,
            transition: 'all var(--transition-fast)',
          }}
          onMouseEnter={(e) => { if (!loading) { e.currentTarget.style.color = 'var(--accent-primary)'; e.currentTarget.style.borderColor = 'var(--accent-border)'; } }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
        >
          {loading ? 'Loading…' : 'Load more'}
        </button>
      )}
    </div>
  );
}
