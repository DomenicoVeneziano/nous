// frontend/src/components/project/AssetTable.tsx
import React, { useState } from 'react';
import type { Asset, Highlight } from '../../types/asset';
import { HighlightText } from '../shared/HighlightText';

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

  const sorted = [...assets].sort((a, b) => {
    const av = a[sortKey] ?? '';
    const bv = b[sortKey] ?? '';
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('asc'); }
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

  return (
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
            <th style={{ ...thStyle, cursor: 'default' }}>Technologies</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((asset, i) => {
            const selected = selectedIds.has(asset.id);
            const highlights = (asset as Asset & { highlights?: Highlight[] }).highlights;
            const hostnameHls = getHighlightsFor(highlights, 'hostname');
            const titleHls = getHighlightsFor(highlights, 'title');
            const techHls = getHighlightsFor(highlights, 'tech');
            const hiddenBadges = getHiddenMatchBadges(highlights);

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
                  <HighlightText text={asset.asset} spans={hostnameHls} />
                </td>
                <td style={{
                  ...tdStyle, fontFamily: 'var(--font-mono)',
                  color: statusColor(asset.status_code), fontWeight: 600, fontSize: 12,
                }}>
                  {asset.status_code ?? '-'}
                </td>
                <td style={{
                  ...tdStyle, maxWidth: 200, overflow: 'hidden',
                  textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-secondary)',
                }}>
                  {asset.title
                    ? <HighlightText text={asset.title} spans={titleHls} />
                    : '-'}
                </td>
                <td style={{ ...tdStyle, fontFamily: 'var(--font-mono)', color: 'var(--text-code)', fontSize: 12 }}>
                  {asset.content_length != null ? asset.content_length.toLocaleString() : '-'}
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
  );
}
