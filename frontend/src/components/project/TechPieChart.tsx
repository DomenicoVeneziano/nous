// frontend/src/components/project/TechPieChart.tsx
import React, { useMemo } from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import type { Asset } from '../../types/asset';

interface Props { assets: Asset[]; }

const COLORS = ['#7c6bff', '#3ecf8e', '#60a5fa', '#fbbf24', '#f87171', '#a78bfa', '#34d399', '#fb923c'];

const tooltipStyle: React.CSSProperties = {
  backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-md)', color: 'var(--text-primary)', fontSize: 12,
  fontFamily: 'var(--font-mono)', boxShadow: 'var(--shadow-elevated)', padding: '8px 12px',
};

export default function TechPieChart({ assets }: Props) {
  const data = useMemo(() => {
    const counts: Record<string, number> = {};
    assets.forEach((a) => { (a.technologies || []).forEach((t) => { counts[t] = (counts[t] || 0) + 1; }); });
    return Object.entries(counts).sort(([, a], [, b]) => b - a).slice(0, 10).map(([name, value]) => ({ name, value }));
  }, [assets]);

  if (data.length === 0) return null;

  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: 18, boxShadow: 'var(--shadow-card)' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14 }}>
        Top Technologies
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%"
            outerRadius={80} innerRadius={40} stroke="var(--bg-base)" strokeWidth={2} paddingAngle={2}
          >
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: 'var(--text-primary)' }} labelStyle={{ color: 'var(--text-secondary)' }} />
        </PieChart>
      </ResponsiveContainer>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
        {data.map((d, i) => (
          <span key={d.name} style={{ fontSize: 10, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{
              width: 10, height: 10, borderRadius: 2, display: 'inline-block', flexShrink: 0,
              backgroundColor: COLORS[i % COLORS.length],
            }} />
            {d.name} <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>({d.value})</span>
          </span>
        ))}
      </div>
    </div>
  );
}
