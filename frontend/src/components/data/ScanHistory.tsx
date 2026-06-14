// frontend/src/components/data/ScanHistory.tsx
import React, { useState } from 'react';
import type { ScanJob } from '../../types/scan';
import { cancelJob, clearHistory } from '../../api/scans';
import StatusBadge from '../shared/StatusBadge';
import { Trash2 } from 'lucide-react';

interface Props {
  jobs: ScanJob[];
  onRefresh: () => void;
}

function statusVariant(status: string) {
  switch (status) {
    case 'done': return 'success' as const;
    case 'failed': return 'error' as const;
    case 'cancelled': return 'muted' as const;
    case 'timed_out': return 'warning' as const;
    default: return 'muted' as const;
  }
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '-';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function ScanHistory({ jobs, onRefresh }: Props) {
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  const handleDelete = async (jobId: string) => {
    try {
      await cancelJob(jobId);
      onRefresh();
    } catch { /* ignore */ }
  };

  const handleClearAll = async () => {
    setClearing(true);
    try {
      await clearHistory();
      onRefresh();
    } catch { /* ignore */ }
    setClearing(false);
    setConfirmClear(false);
  };

  const thStyle: React.CSSProperties = {
    background: 'var(--bg-elevated)', color: 'var(--text-muted)',
    fontSize: 11, fontWeight: 600,
    textTransform: 'uppercase', letterSpacing: '0.08em',
    padding: '10px 14px', textAlign: 'left', whiteSpace: 'nowrap',
    borderBottom: '1px solid var(--border-default)',
  };

  const tdStyle: React.CSSProperties = {
    padding: '9px 14px', borderBottom: '1px solid var(--border-subtle)', fontSize: 14,
  };

  const iconBtnStyle: React.CSSProperties = {
    background: 'transparent', border: 'none', color: 'var(--text-muted)',
    cursor: 'pointer', padding: 4, borderRadius: 4, display: 'flex',
    alignItems: 'center', justifyContent: 'center',
    transition: 'color var(--transition-fast)',
  };

  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 8, overflow: 'hidden',
      boxShadow: 'var(--shadow-card)',
    }}>
      <div style={{
        padding: '14px 18px', borderBottom: '1px solid var(--border-subtle)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
          Scan History
        </span>
        {jobs.length > 0 && (
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
              <Trash2 size={12} /> Clear History
            </button>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>Delete all entries?</span>
              <button
                onClick={handleClearAll}
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
      <div style={{ overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={thStyle}>Type</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Duration</th>
              <th style={thStyle}>Started</th>
              <th style={thStyle}>Error</th>
              <th style={{ ...thStyle, width: 40 }}></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job, i) => (
              <tr
                key={job.id}
                style={{
                  background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
                  transition: 'background var(--transition-fast)',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-hover)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)'; }}
              >
                <td style={{ ...tdStyle, fontFamily: 'var(--font-mono)', color: 'var(--text-code)', fontWeight: 500 }}>
                  {job.scan_type}
                </td>
                <td style={tdStyle}>
                  <StatusBadge variant={statusVariant(job.status)}>{job.status.toUpperCase()}</StatusBadge>
                </td>
                <td style={{ ...tdStyle, fontFamily: 'var(--font-mono)', color: 'var(--text-code)' }}>
                  {formatDuration(job.duration_s)}
                </td>
                <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
                  {job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
                </td>
                <td style={{
                  ...tdStyle, color: 'var(--status-error)', fontSize: 11,
                  maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  fontFamily: 'var(--font-mono)',
                }}>
                  {job.error_msg || '-'}
                </td>
                <td style={{ ...tdStyle, textAlign: 'center' }}>
                  <button
                    onClick={() => handleDelete(job.id)}
                    style={iconBtnStyle}
                    onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
                    title="Delete entry"
                  >
                    <Trash2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
