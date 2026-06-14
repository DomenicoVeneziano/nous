import React, { useRef, useLayoutEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { clearScanOutput } from '../../api/scans';

interface Props {
  lines: string[];
  // Absolute index of lines[0] within the full stream, for stable keys/numbers.
  lineOffset?: number;
  activeJob?: { scan_type: string; id: string } | null;
}

// How long after the page opens we keep the view pinned to the newest line
// while the WebSocket replays the backlog. After this, the monitor freezes so
// live output lands below the fold and the view stays where the user left it.
const OPEN_FOLLOW_MS = 1000;

// Semantic colours for scan output
function lineColor(line: string): string {
  if (line.includes('[!]') || line.toLowerCase().includes('error')) return 'var(--status-error)';
  if (line.includes('[*]') || line.toLowerCase().includes('warning')) return 'var(--status-warning)';
  if (line.includes('[+]') || line.toLowerCase().includes('found')) return 'var(--status-success)';
  return 'var(--text-code)';
}

export default function ScanMonitor({ lines, lineOffset = 0, activeJob }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mountedAt = useRef(Date.now());
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Jump to the newest line only during the brief window after the page opens
  // (covers the WebSocket backlog replay). Once that window passes we never
  // auto-scroll again, so the view stays exactly where the user leaves it.
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (Date.now() - mountedAt.current < OPEN_FOLLOW_MS) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines]);

  const handleClear = async () => {
    setClearing(true);
    try {
      await clearScanOutput();
    } catch { /* ignore */ }
    setClearing(false);
    setConfirmClear(false);
  };

  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 8, overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
      boxShadow: 'var(--shadow-card)',
    }}>
      <div style={{
        padding: '10px 18px', borderBottom: '1px solid var(--border-subtle)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Scan Monitor</span>
          {activeJob && (
            <>
              <div className="live-dot" />
              <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                {activeJob.scan_type} / {activeJob.id.slice(0, 8)}
              </span>
            </>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {lines.length > 0 && (
            !confirmClear ? (
              <button
                onClick={() => setConfirmClear(true)}
                style={{
                  background: 'transparent', color: 'var(--text-muted)', border: 'none',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                  fontSize: 11, padding: '4px 8px', borderRadius: 4,
                  transition: 'color var(--transition-fast)',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-primary)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
              >
                <Trash2 size={12} /> Clear Output
              </button>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>Clear output?</span>
                <button
                  onClick={handleClear}
                  disabled={clearing}
                  style={{
                    background: 'var(--status-error-bg)', color: 'var(--status-error)',
                    border: '1px solid var(--status-error-border)',
                    borderRadius: 4, padding: '3px 10px', fontSize: 11, fontWeight: 600,
                    cursor: clearing ? 'not-allowed' : 'pointer',
                  }}
                >{clearing ? 'Clearing...' : 'Yes'}</button>
                <button
                  onClick={() => setConfirmClear(false)}
                  style={{
                    background: 'transparent', color: 'var(--text-muted)',
                    border: '1px solid var(--border-default)',
                    borderRadius: 4, padding: '3px 10px', fontSize: 11, cursor: 'pointer',
                  }}
                >No</button>
              </div>
            )
          )}
        </div>
      </div>
      <div
        ref={containerRef}
        style={{
          backgroundColor: 'var(--bg-void)',
          backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 28px, rgba(124,107,255,0.015) 28px, rgba(124,107,255,0.015) 29px)',
          padding: 0,
          minHeight: 220, maxHeight: 400,
          overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 13, lineHeight: 1.7,
        }}
      >
        {lines.length === 0 ? (
          <div style={{ padding: '40px 18px', color: 'var(--text-muted)', textAlign: 'center' }}>
            Waiting for scan output...
          </div>
        ) : (
          // Oldest at top, newest at bottom. Keyed by absolute index so rows
          // stay stable (and line numbers stay truthful) as the buffer slides.
          lines.map((line, i) => {
            const absIndex = lineOffset + i;
            return (
              <div key={absIndex} style={{
                display: 'flex', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                padding: '0 14px',
                background: absIndex % 2 === 0 ? 'transparent' : 'rgba(124,107,255,0.01)',
              }}>
                <span style={{
                  color: 'var(--text-muted)', minWidth: 52, textAlign: 'right',
                  paddingRight: 14, userSelect: 'none', fontSize: 12,
                  borderRight: '1px solid var(--border-subtle)',
                  marginRight: 14,
                }}>
                  {absIndex + 1}
                </span>
                <span style={{ color: lineColor(line), flex: 1 }}>
                  {line}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
