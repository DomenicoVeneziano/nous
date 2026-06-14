// frontend/src/components/dashboard/AssetPieChart.tsx
import React from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface Props {
  data: { name: string; value: number }[];
  title: string;
}

const COLORS = ['#7c6bff', '#3ecf8e', '#60a5fa', '#fbbf24', '#f87171', '#a78bfa', '#34d399', '#fb923c'];

const tooltipStyle: React.CSSProperties = {
  backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-md)', color: 'var(--text-primary)', fontSize: 12,
  fontFamily: 'var(--font-mono)', boxShadow: 'var(--shadow-elevated)', padding: '8px 12px',
};

export default function AssetPieChart({ data, title }: Props) {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)', padding: 20,
      boxShadow: 'var(--shadow-card)',
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16 }}>
        {title}
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name"
            cx="50%" cy="50%" outerRadius={90} innerRadius={50}
            stroke="var(--bg-base)" strokeWidth={2} paddingAngle={2}
          >
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: 'var(--text-primary)' }} labelStyle={{ color: 'var(--text-secondary)' }} />
        </PieChart>
      </ResponsiveContainer>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8, justifyContent: 'center' }}>
        {data.map((d, i) => (
          <span key={d.name} style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{
              width: 10, height: 10, borderRadius: 3, display: 'inline-block', flexShrink: 0,
              backgroundColor: COLORS[i % COLORS.length],
            }} />
            {d.name}
          </span>
        ))}
      </div>
    </div>
  );
}
