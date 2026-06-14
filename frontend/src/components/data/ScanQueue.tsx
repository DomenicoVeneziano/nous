// frontend/src/components/data/ScanQueue.tsx
import React from 'react';
import type { ScanJob } from '../../types/scan';
import StatusBadge from '../shared/StatusBadge';
import { cancelJob } from '../../api/scans';
import { X } from 'lucide-react';

interface Props {
  jobs: ScanJob[];
  onRefresh: () => void;
}

export default function ScanQueue({ jobs, onRefresh }: Props) {
  const handleCancel = async (id: string) => {
    await cancelJob(id);
    onRefresh();
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
        fontSize: 13, fontWeight: 600, color: '#e8e8e8',
      }}>
        Scan Queue
      </div>
      {jobs.length === 0 ? (
        <div style={{
          padding: 28, textAlign: 'center', color: '#484848',
          fontSize: 12, fontFamily: 'var(--font-mono)',
        }}>
          No jobs in queue
        </div>
      ) : (
        jobs.map((job) => (
          <div key={job.id} style={{
            display: 'flex', alignItems: 'center', padding: '11px 18px',
            borderBottom: '1px solid var(--border-subtle)', gap: 12,
            borderLeft: job.status === 'running'
              ? '2px solid var(--accent-primary)'
              : '2px solid transparent',
            transition: 'background var(--transition-fast)',
          }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-hover)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 11, color: '#484848',
              minWidth: 24, textAlign: 'center', fontWeight: 600,
            }}>
              {job.queue_pos ?? '-'}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#c8c8c8', flex: 1, fontWeight: 500 }}>
              {job.scan_type}
            </span>
            <StatusBadge variant={job.status === 'running' ? 'running' : 'warning'}>
              {job.status.toUpperCase()}
            </StatusBadge>
            {(job.status === 'queued' || job.status === 'running') && (
              <button
                onClick={() => handleCancel(job.id)}
                style={{
                  background: 'transparent', border: 'none', cursor: 'pointer',
                  color: '#484848', padding: 3, borderRadius: 4,
                  transition: 'color var(--transition-fast)',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = '#484848'; }}
                title="Cancel"
              >
                <X size={13} />
              </button>
            )}
          </div>
        ))
      )}
    </div>
  );
}
