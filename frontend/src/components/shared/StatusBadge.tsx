// frontend/src/components/shared/StatusBadge.tsx
import React from 'react';

type Variant = 'active' | 'success' | 'warning' | 'error' | 'muted' | 'running';

const styles: Record<Variant, React.CSSProperties> = {
  active: {
    backgroundColor: 'var(--accent-subtle)',
    color: 'var(--accent-primary)',
    border: '1px solid var(--accent-border)',
  },
  success: {
    backgroundColor: 'var(--status-success-bg)',
    color: 'var(--status-success)',
    border: '1px solid var(--status-success-border)',
  },
  warning: {
    backgroundColor: 'var(--status-warning-bg)',
    color: 'var(--status-warning)',
    border: '1px solid var(--status-warning-border)',
  },
  error: {
    backgroundColor: 'var(--status-error-bg)',
    color: 'var(--status-error)',
    border: '1px solid var(--status-error-border)',
  },
  muted: {
    backgroundColor: 'var(--status-muted-bg)',
    color: 'var(--text-muted)',
    border: '1px solid var(--status-muted-border)',
  },
  running: {
    backgroundColor: 'var(--status-running-bg)',
    color: 'var(--status-running)',
    border: '1px solid var(--status-running-border)',
    boxShadow: '0 0 8px rgba(167,139,250,0.15)',
  },
};

const base: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, padding: '3px 8px', borderRadius: 4,
  fontFamily: 'var(--font-mono)', letterSpacing: '0.06em',
  display: 'inline-block', whiteSpace: 'nowrap',
};

interface Props { variant: Variant; children: React.ReactNode; }

export default function StatusBadge({ variant, children }: Props) {
  return <span style={{ ...base, ...styles[variant] }}>{children}</span>;
}
