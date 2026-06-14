// frontend/src/components/project/FindingsSearchView.tsx
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Search, X, ChevronLeft, ChevronRight } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type { FindingSearchResult, Severity } from '../../types/finding';
import { searchFindings } from '../../api/findings';
import { mdComponents } from '../shared/markdownComponents';

interface Props {
  projectId: string;
}

const SEVERITY_STYLE: Record<Severity, { color: string; bg: string; border: string }> = {
  informative: { color: 'var(--status-info)',    bg: 'var(--status-info-bg)',    border: 'var(--status-info-border)'    },
  low:         { color: 'var(--status-success)', bg: 'var(--status-success-bg)', border: 'var(--status-success-border)' },
  medium:      { color: 'var(--status-warning)', bg: 'var(--status-warning-bg)', border: 'var(--status-warning-border)' },
  high:        { color: '#f97316',               bg: 'rgba(249,115,22,0.10)',    border: 'rgba(249,115,22,0.25)'        },
  critical:    { color: 'var(--status-error)',   bg: 'var(--status-error-bg)',   border: 'var(--status-error-border)'   },
};

const SEVERITIES: Severity[] = ['informative', 'low', 'medium', 'high', 'critical'];

function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.informative;
  return (
    <span style={{
      fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
      letterSpacing: '0.07em', padding: '3px 8px', borderRadius: 'var(--radius-sm)',
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
      textTransform: 'uppercase', flexShrink: 0,
    }}>
      {severity}
    </span>
  );
}

const thStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  padding: '8px 12px', textAlign: 'left',
  borderBottom: '1px solid var(--border-subtle)',
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '10px 12px', fontSize: 12,
  borderBottom: '1px solid var(--border-subtle)',
  verticalAlign: 'middle',
};

export default function FindingsSearchView({ projectId }: Props) {
  const [findings, setFindings] = useState<FindingSearchResult[]>([]);
  const [query, setQuery] = useState('');
  const [severity, setSeverity] = useState('');
  const [loading, setLoading] = useState(false);
  const [overlayIdx, setOverlayIdx] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const results = await searchFindings({
          project_id: projectId,
          query: query.trim() || undefined,
          severity: severity || undefined,
          limit: 500,
        });
        setFindings(results);
      } catch {
        setFindings([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [projectId, query, severity]);

  const closeOverlay = useCallback(() => setOverlayIdx(null), []);
  const prevFinding = useCallback(() => {
    if (overlayIdx !== null && overlayIdx > 0) setOverlayIdx(overlayIdx - 1);
  }, [overlayIdx]);
  const nextFinding = useCallback(() => {
    if (overlayIdx !== null && overlayIdx < findings.length - 1) setOverlayIdx(overlayIdx + 1);
  }, [overlayIdx, findings.length]);

  useEffect(() => {
    if (overlayIdx === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeOverlay();
      if (e.key === 'ArrowLeft') prevFinding();
      if (e.key === 'ArrowRight') nextFinding();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [overlayIdx, prevFinding, nextFinding, closeOverlay]);

  const formatDate = (iso: string) => new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  });

  return (
    <div>
      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}>
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', gap: 8,
          background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)', padding: '8px 12px',
        }}>
          <Search size={14} color="var(--text-muted)" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search finding titles and bodies..."
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              color: 'var(--text-primary)', fontSize: 12, fontFamily: 'var(--font-mono)',
            }}
          />
          {query && (
            <button onClick={() => setQuery('')} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', padding: 0 }}>
              <X size={13} color="var(--text-muted)" />
            </button>
          )}
        </div>
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          style={{
            background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)', color: severity ? 'var(--text-primary)' : 'var(--text-muted)',
            padding: '8px 10px', fontSize: 12, fontFamily: 'var(--font-mono)',
            cursor: 'pointer', outline: 'none',
          }}
        >
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>
      </div>

      {/* Results */}
      <div className="card" style={{ overflow: 'hidden', padding: 0 }}>
        {loading ? (
          <div style={{ padding: 24, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>
            Loading findings...
          </div>
        ) : findings.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
            {query || severity ? 'No findings match your filters.' : 'No findings recorded for this project yet.'}
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-surface)' }}>
                <th style={{ ...thStyle, width: 110 }}>Severity</th>
                <th style={thStyle}>Title</th>
                <th style={{ ...thStyle, width: 200 }}>Asset</th>
                <th style={{ ...thStyle, width: 120 }}>Found</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((f, idx) => (
                <tr
                  key={f.id}
                  onClick={() => setOverlayIdx(idx)}
                  style={{ cursor: 'pointer', transition: 'background var(--transition-fast)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-surface)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                >
                  <td style={tdStyle}><SeverityBadge severity={f.severity as Severity} /></td>
                  <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>{f.title}</td>
                  <td style={{ ...tdStyle, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    {f.asset_hostname}
                  </td>
                  <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 11 }}>
                    {formatDate(f.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {findings.length > 0 && !loading && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8, textAlign: 'right' }}>
          {findings.length} finding{findings.length !== 1 ? 's' : ''}
        </div>
      )}

      {/* Finding detail overlay */}
      {overlayIdx !== null && findings[overlayIdx] && (() => {
        const f = findings[overlayIdx];
        return (
          <div
            onClick={closeOverlay}
            style={{
              position: 'fixed', inset: 0, zIndex: 1000,
              background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(2px)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-lg)', width: '100%', maxWidth: 680,
                maxHeight: '80vh', display: 'flex', flexDirection: 'column',
                boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
              }}
            >
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '14px 16px', borderBottom: '1px solid var(--border-subtle)', flexShrink: 0,
              }}>
                <SeverityBadge severity={f.severity as Severity} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{f.title}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>
                    {f.asset_hostname}
                  </div>
                </div>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginRight: 8 }}>
                  {overlayIdx + 1} / {findings.length}
                </span>
                <button
                  onClick={closeOverlay}
                  title="Close (Esc)"
                  style={{
                    background: 'transparent', border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
                    padding: '3px 6px', cursor: 'pointer', display: 'flex', alignItems: 'center',
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-primary)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
                ><X size={13} /></button>
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px' }}>
                {f.body ? (
                  <ReactMarkdown components={mdComponents}>{f.body}</ReactMarkdown>
                ) : (
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>No description.</span>
                )}
              </div>
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '10px 16px', borderTop: '1px solid var(--border-subtle)', flexShrink: 0,
              }}>
                <button
                  onClick={prevFinding}
                  disabled={overlayIdx === 0}
                  title="Previous (←)"
                  style={{
                    background: 'transparent', border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)', color: overlayIdx === 0 ? 'var(--text-disabled)' : 'var(--text-muted)',
                    padding: '5px 12px', fontSize: 11, cursor: overlayIdx === 0 ? 'not-allowed' : 'pointer',
                    display: 'flex', alignItems: 'center', gap: 4, opacity: overlayIdx === 0 ? 0.4 : 1,
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { if (overlayIdx > 0) e.currentTarget.style.color = 'var(--text-primary)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = overlayIdx === 0 ? 'var(--text-disabled)' : 'var(--text-muted)'; }}
                >
                  <ChevronLeft size={13} /> Previous
                </button>
                <button
                  onClick={nextFinding}
                  disabled={overlayIdx === findings.length - 1}
                  title="Next (→)"
                  style={{
                    background: 'transparent', border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)',
                    color: overlayIdx === findings.length - 1 ? 'var(--text-disabled)' : 'var(--text-muted)',
                    padding: '5px 12px', fontSize: 11,
                    cursor: overlayIdx === findings.length - 1 ? 'not-allowed' : 'pointer',
                    display: 'flex', alignItems: 'center', gap: 4,
                    opacity: overlayIdx === findings.length - 1 ? 0.4 : 1,
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { if (overlayIdx < findings.length - 1) e.currentTarget.style.color = 'var(--text-primary)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = overlayIdx === findings.length - 1 ? 'var(--text-disabled)' : 'var(--text-muted)'; }}
                >
                  Next <ChevronRight size={13} />
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
