// frontend/src/components/layout/GlobalSearch.tsx
import React, { useState, useRef, useEffect } from 'react';
import { Search, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSearch } from '../../hooks/useSearch';
import ExportButton from '../shared/ExportButton';
import { HighlightText } from '../shared/HighlightText';
import type { AssetSearchResult } from '../../types/asset';

// Fields not shown as text in the result row — surfaced as match badges instead.
// Kept in sync with HIDDEN_FIELDS in AssetTable.tsx.
const HIDDEN_FIELDS = new Set(['content', 'header', 'body', 'dns', 'url', 'date', 'type', 'severity', 'vuln', 'content_length']);

export default function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const { results, loading, query, search } = useSearch();
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleChange = (value: string) => {
    search(value);
    setOpen(true);
  };

  const handleAssetClick = (asset: AssetSearchResult) => {
    setOpen(false);
    search('');
    navigate(`/projects/${asset.project_id}`);
  };

  const handleClear = () => {
    search('');
    setOpen(false);
    inputRef.current?.focus();
  };

  return (
    <div ref={wrapperRef} style={{ position: 'relative' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border-default)', borderRadius: 'var(--radius-md)',
        padding: '5px 10px', width: 260,
        transition: 'border-color var(--transition-fast)',
      }}>
        <Search size={13} color="var(--text-muted)" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => query && setOpen(true)}
          placeholder="Search all assets..."
          style={{
            flex: 1, background: 'transparent', border: 'none', outline: 'none',
            color: 'var(--text-primary)', fontSize: 12, fontFamily: 'var(--font-mono)',
          }}
        />
        {query && (
          <button
            onClick={handleClear}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: 'var(--text-muted)', display: 'flex', padding: 0,
              transition: 'color var(--transition-fast)',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-secondary)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
          >
            <X size={12} />
          </button>
        )}
      </div>

      {open && query && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 6,
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)', borderRadius: 'var(--radius-lg)',
          maxHeight: 340, overflow: 'auto', zIndex: 9999,
          boxShadow: 'var(--shadow-dropdown)',
          animation: 'fadeIn 150ms ease',
        }}>
          {loading && (
            <div style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
              Searching...
            </div>
          )}
          {!loading && results.length === 0 && (
            <div style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: 12 }}>
              No results found
            </div>
          )}
          {!loading && results.map((asset) => {
            const hostnameHls = asset.highlights.filter((h) => h.source === 'hostname');
            const techHls = asset.highlights.filter((h) => h.source === 'tech');
            const seen = new Set<string>();
            for (const h of asset.highlights) {
              if (HIDDEN_FIELDS.has(h.field)) seen.add(h.field);
            }
            const hiddenBadges = [...seen];
            const techs = asset.technologies?.slice(0, 5) ?? [];
            return (
              <button
                key={asset.id}
                onClick={() => handleAssetClick(asset)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  background: 'transparent', border: 'none',
                  borderBottom: '1px solid var(--border-subtle)',
                  padding: '10px 14px', cursor: 'pointer', color: 'var(--text-primary)',
                  transition: 'background var(--transition-fast)',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-code)' }}>
                  <HighlightText text={asset.asset} spans={hostnameHls} />
                </div>
                {techs.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                    {techs.map((t, idx) => {
                      const spans = techHls.filter((h) => h.index === idx);
                      return (
                        <span key={t} style={{
                          fontSize: 10, color: spans.length > 0 ? 'var(--accent-primary)' : 'var(--text-muted)',
                          fontFamily: 'var(--font-mono)',
                        }}>
                          <HighlightText text={t} spans={spans} />
                          {idx < techs.length - 1 && (
                            <span style={{ color: 'var(--text-muted)' }}> / </span>
                          )}
                        </span>
                      );
                    })}
                  </div>
                )}
                {hiddenBadges.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 4 }}>
                    {hiddenBadges.map((badge) => (
                      <span key={badge} style={{
                        fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 600,
                        background: 'var(--status-warning-bg, rgba(255,165,0,0.12))',
                        color: 'var(--status-warning, #f90)',
                        border: '1px solid var(--status-warning-border, rgba(255,165,0,0.3))',
                        borderRadius: 'var(--radius-sm)', padding: '0px 5px',
                      }}>
                        {badge}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            );
          })}
          {!loading && results.length > 0 && (
            <div style={{
              padding: '10px 14px',
              borderTop: '1px solid var(--border-default)',
              display: 'flex', justifyContent: 'flex-end',
            }}>
              <ExportButton query={query} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
