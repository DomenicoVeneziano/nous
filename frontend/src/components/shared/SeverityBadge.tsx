// frontend/src/components/shared/SeverityBadge.tsx
import React from 'react';
import type { Severity } from '../../types/finding';

export const SEVERITY_STYLE: Record<Severity, { color: string; bg: string; border: string }> = {
  informative: { color: 'var(--status-info)',    bg: 'var(--status-info-bg)',    border: 'var(--status-info-border)'    },
  low:         { color: 'var(--status-success)', bg: 'var(--status-success-bg)', border: 'var(--status-success-border)' },
  medium:      { color: 'var(--status-warning)', bg: 'var(--status-warning-bg)', border: 'var(--status-warning-border)' },
  high:        { color: '#f97316',               bg: 'rgba(249,115,22,0.10)',    border: 'rgba(249,115,22,0.25)'        },
  critical:    { color: 'var(--status-error)',   bg: 'var(--status-error-bg)',   border: 'var(--status-error-border)'   },
};

export default function SeverityBadge({ severity }: { severity: Severity }) {
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
