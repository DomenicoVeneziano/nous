// frontend/src/components/dashboard/StatsBar.tsx
import React from 'react';

interface StatCard {
  label: string;
  value: string | number;
}

interface Props {
  stats: StatCard[];
}

export default function StatsBar({ stats }: Props) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(stats.length, 6)}, 1fr)`, gap: 12 }}>
      {stats.map((stat, i) => (
        <div key={i} style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
          padding: '18px 20px',
          boxShadow: 'var(--shadow-card)',
          position: 'relative',
          overflow: 'hidden',
          transition: 'border-color var(--transition-fast)',
        }}>
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0, height: 1,
            background: 'linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.08), transparent)',
          }} />
          <div style={{
            fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10,
          }}>
            {stat.label}
          </div>
          <div className="stat-value" style={{
            fontSize: 28, fontWeight: 600, color: 'var(--text-primary)',
            fontFamily: 'var(--font-mono)',
            lineHeight: 1,
          }}>
            {stat.value}
          </div>
        </div>
      ))}
    </div>
  );
}
