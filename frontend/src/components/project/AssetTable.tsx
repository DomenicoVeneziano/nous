// frontend/src/components/project/AssetTable.tsx
import React, { useState, useMemo, useEffect } from 'react';
import type { Asset, Highlight } from '../../types/asset';
import { NEW_TAG_LABEL } from '../../types/tag';
import { HighlightText } from '../shared/HighlightText';
import TagChip, { orderTags } from '../shared/TagChip';

const PAGE_SIZE_OPTIONS = [100, 250, 500, 1000];

// Chips shown inline per row before collapsing into a "+n tags" counter. Source
// tags accumulate, so an established asset can carry a lot of them; the cap
// keeps the row readable and the asset panel holds the full list.
const ROW_TAG_LIMIT = 4;

// Hostname cell cap: a long hostname must not widen the table and put a
// horizontal scrollbar on the whole page.
const HOSTNAME_MAX_WIDTH = 340;

// Title cell cap: page titles come straight from the crawled markup and CMS
// pages routinely emit a few hundred characters, which would widen the table
// the same way.
const TITLE_MAX_WIDTH = 260;

interface Props {
  assets: Asset[];
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onSelectAll: () => void;
  onAssetClick: (asset: Asset) => void;
}

// Semantic status colours
function statusColor(code: number | null): string {
  if (!code) return 'var(--text-muted)';
  if (code >= 200 && code < 300) return 'var(--status-success)';
  if (code >= 300 && code < 400) return 'var(--status-info)';
  if (code >= 400 && code < 500) return 'var(--status-warning)';
  return 'var(--status-error)';
}

type SortKey = 'asset' | 'status_code' | 'title' | 'content_length';

// Fields that are not visible as table columns — shown as small match badges
const HIDDEN_FIELDS = new Set(['content', 'header', 'body', 'dns', 'url', 'date', 'type', 'severity', 'vuln', 'content_length']);

function getHighlightsFor(highlights: Highlight[] | undefined, source: string): Highlight[] {
  return (highlights || []).filter((h) => h.source === source);
}

function getHiddenMatchBadges(highlights: Highlight[] | undefined): string[] {
  if (!highlights) return [];
  const seen = new Set<string>();
  for (const h of highlights) {
    if (HIDDEN_FIELDS.has(h.field)) {
      // For vuln: show "vuln" as the label (field), not the underlying source
      seen.add(h.field === 'vuln' ? 'vuln' : h.field);
    }
  }
  return Array.from(seen);
}

export default function AssetTable({ assets, selectedIds, onToggleSelect, onSelectAll, onAssetClick }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('asset');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [pageSize, setPageSize] = useState(250);
  const [page, setPage] = useState(0);

  // Sort the full set (so ordering and pagination span every asset, not just
  // the rows currently on screen); memoised so toggling a checkbox doesn't
  // re-sort tens of thousands of rows on every render.
  const sorted = useMemo(() => {
    return [...assets].sort((a, b) => {
      const av = a[sortKey] ?? '';
      const bv = b[sortKey] ?? '';
      const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [assets, sortKey, sortDir]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));

  // Keep the current page in range when the set shrinks (search, deletion) or
  // the page size changes.
  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1);
  }, [pageCount, page]);

  const start = page * pageSize;
  const pageItems = sorted.slice(start, start + pageSize);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('asc'); }
    setPage(0);
  };

  const sortIndicator = (key: SortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : '';

  const thStyle: React.CSSProperties = {
    background: 'var(--bg-elevated)', color: 'var(--text-muted)',
    fontSize: 11, fontWeight: 600,
    textTransform: 'uppercase', letterSpacing: '0.08em',
    padding: '10px 16px', textAlign: 'left', cursor: 'pointer',
    position: 'sticky', top: 0, zIndex: 1,
    borderBottom: '1px solid var(--border-default)', whiteSpace: 'nowrap',
  };

  const tdStyle: React.CSSProperties = {
    padding: '9px 16px', borderBottom: '1px solid var(--border-subtle)', fontSize: 14,
  };

  const btnStyle = (disabled: boolean): React.CSSProperties => ({
    background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
    border: '1px solid var(--border-default)', borderRadius: 6,
    padding: '4px 12px', fontSize: 12, fontWeight: 500,
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1,
    fontFamily: 'var(--font-mono)',
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}>
    <div style={{
      overflow: 'auto',
      border: '1px solid var(--border-subtle)', borderRadius: 8,
      boxShadow: 'var(--shadow-card)',
    }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ ...thStyle, width: 32, cursor: 'default' }}>
              <input type="checkbox" onChange={onSelectAll} checked={selectedIds.size === assets.length && assets.length > 0} />
            </th>
            <th style={thStyle} onClick={() => handleSort('asset')}>
              Hostname{sortIndicator('asset')}
            </th>
            <th style={thStyle} onClick={() => handleSort('status_code')}>
              Status{sortIndicator('status_code')}
            </th>
            <th style={thStyle} onClick={() => handleSort('title')}>
              Title{sortIndicator('title')}
            </th>
            <th style={thStyle} onClick={() => handleSort('content_length')}>
              Length{sortIndicator('content_length')}
            </th>
            <th style={{ ...thStyle, cursor: 'default' }}>Tags</th>
            <th style={{ ...thStyle, cursor: 'default' }}>Technologies</th>
          </tr>
        </thead>
        <tbody>
          {pageItems.map((asset, i) => {
            const selected = selectedIds.has(asset.id);
            const highlights = (asset as Asset & { highlights?: Highlight[] }).highlights;
            const hostnameHls = getHighlightsFor(highlights, 'hostname');
            const titleHls = getHighlightsFor(highlights, 'title');
            const techHls = getHighlightsFor(highlights, 'tech');
            const hiddenBadges = getHiddenMatchBadges(highlights);
            // Matched by snippet text rather than list index: the server builds
            // its tag list in its own order, and the chips are reordered here.
            const tagHls = getHighlightsFor(highlights, 'tag');
            // "New!" is always shown — it is the reason to look at the row at
            // all — and only the stored tags are capped.
            const ordered = orderTags(asset.tags || []);
            // A tag that matched the query has to survive the cap: reading
            // order puts discovery sources first, so a matching user tag can
            // otherwise collapse into "+n tags" and leave the row with nothing
            // on screen explaining why the search returned it.
            const matched = new Set(tagHls.map((h) => h.snippet));
            const prioritized = matched.size > 0
              ? [...ordered.filter((t) => matched.has(t.name)), ...ordered.filter((t) => !matched.has(t.name))]
              : ordered;
            const visibleTags = prioritized.slice(0, ROW_TAG_LIMIT);
            const hiddenTagCount = prioritized.length - visibleTags.length;

            return (
              <tr
                key={asset.id}
                onClick={() => onAssetClick(asset)}
                style={{
                  backgroundColor: selected ? 'var(--bg-selected)' : (i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-surface)'),
                  cursor: 'pointer',
                  transition: 'background var(--transition-fast)',
                  borderLeft: selected ? '2px solid var(--accent-primary)' : '2px solid transparent',
                }}
                onMouseEnter={(e) => {
                  if (!selected) e.currentTarget.style.backgroundColor = 'var(--bg-hover)';
                }}
                onMouseLeave={(e) => {
                  if (!selected) e.currentTarget.style.backgroundColor = i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-surface)';
                }}
              >
                <td style={tdStyle} onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selected} onChange={() => onToggleSelect(asset.id)} />
                </td>
                <td style={{
                  ...tdStyle, fontFamily: 'var(--font-mono)',
                  color: 'var(--text-code)', fontSize: 13, fontWeight: 500,
                }}>
                  {/* Capped on an inner block, not the <td>: auto table layout
                      ignores a cell's max-width (CSS 2.1 17.5.2), so bounding
                      the column has to happen inside it. The full hostname stays
                      in the DOM so it remains selectable and find-in-page-able,
                      and the highlight spans keep their absolute offsets. */}
                  <span title={asset.asset} style={{
                    display: 'block', maxWidth: HOSTNAME_MAX_WIDTH, overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    <HighlightText text={asset.asset} spans={hostnameHls} />
                  </span>
                </td>
                <td style={{
                  ...tdStyle, fontFamily: 'var(--font-mono)',
                  color: statusColor(asset.status_code), fontWeight: 600, fontSize: 12,
                }}>
                  {asset.status_code ?? '-'}
                </td>
                <td style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                  {/* Same reason as the hostname cell: the cap lives on an inner
                      block because auto table layout ignores max-width on a
                      <td>. The title is never sliced in JS either — the
                      highlight spans are absolute offsets into the full string. */}
                  <span
                    title={asset.title || undefined}
                    style={{
                      display: 'block', maxWidth: TITLE_MAX_WIDTH, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}
                  >
                    {asset.title
                      ? <HighlightText text={asset.title} spans={titleHls} />
                      : '-'}
                  </span>
                </td>
                <td style={{ ...tdStyle, fontFamily: 'var(--font-mono)', color: 'var(--text-code)', fontSize: 12 }}>
                  {asset.content_length != null ? asset.content_length.toLocaleString() : '-'}
                </td>
                <td style={tdStyle}>
                  {visibleTags.length === 0 && !asset.is_new ? (
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>-</span>
                  ) : (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
                      {asset.is_new && (
                        <TagChip
                          label={NEW_TAG_LABEL}
                          variant="new"
                          title="First seen by the most recent recon scan"
                          spans={tagHls.filter((h) => h.snippet === NEW_TAG_LABEL)}
                        />
                      )}
                      {visibleTags.map((tag) => (
                        <TagChip
                          key={tag.id}
                          label={tag.name}
                          variant={tag.is_system ? 'system' : 'user'}
                          color={tag.color}
                          title={tag.is_system ? `Discovery source: ${tag.name}` : tag.name}
                          spans={tagHls.filter((h) => h.snippet === tag.name)}
                        />
                      ))}
                      {hiddenTagCount > 0 && (
                        <span style={{
                          fontSize: 10, color: 'var(--text-muted)',
                          fontFamily: 'var(--font-mono)', textDecoration: 'underline dotted',
                        }}>
                          +{hiddenTagCount} tag{hiddenTagCount === 1 ? '' : 's'}
                        </span>
                      )}
                    </div>
                  )}
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {(asset.technologies || []).slice(0, 4).map((t, idx) => {
                      const techSpans = techHls.filter((h) => h.index === idx);
                      return (
                        <span key={t} style={{
                          background: 'var(--accent-subtle)',
                          color: 'var(--accent-primary)',
                          border: techSpans.length > 0
                            ? '1px solid var(--accent-primary)'
                            : '1px solid var(--accent-border)',
                          borderRadius: 'var(--radius-sm)', padding: '1px 6px', fontSize: 10,
                          fontFamily: 'var(--font-mono)', fontWeight: 500,
                        }}>
                          <HighlightText text={t} spans={techSpans} />
                        </span>
                      );
                    })}
                    {(asset.technologies || []).length > 4 && (
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                        +{asset.technologies.length - 4}
                      </span>
                    )}
                    {hiddenBadges.map((badge) => (
                      <span key={badge} style={{
                        background: 'var(--status-warning-bg, rgba(255,165,0,0.12))',
                        color: 'var(--status-warning, #f90)',
                        border: '1px solid var(--status-warning-border, rgba(255,165,0,0.3))',
                        borderRadius: 'var(--radius-sm)', padding: '1px 6px', fontSize: 10,
                        fontFamily: 'var(--font-mono)', fontWeight: 500,
                      }}>
                        {badge}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>

      {sorted.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, flexWrap: 'wrap', padding: '0 2px',
          fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
        }}>
          <span>
            Showing {start + 1}–{Math.min(start + pageSize, sorted.length)} of {sorted.length.toLocaleString()}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Per page
              <select
                value={pageSize}
                onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }}
                style={{
                  background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
                  borderRadius: 6, color: 'var(--text-primary)', padding: '3px 6px',
                  fontSize: 12, cursor: 'pointer', fontFamily: 'var(--font-mono)',
                }}
              >
                {PAGE_SIZE_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <button style={btnStyle(page <= 0)} disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Prev</button>
            <span>Page {page + 1} of {pageCount}</span>
            <button style={btnStyle(page >= pageCount - 1)} disabled={page >= pageCount - 1} onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}>Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
