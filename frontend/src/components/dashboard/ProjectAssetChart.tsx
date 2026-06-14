// frontend/src/components/dashboard/ProjectAssetChart.tsx
import React from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface ProjectSlice {
  name: string;
  value: number;
}

interface Props {
  data: ProjectSlice[];
}

const COLORS = ['#7c6bff', '#3ecf8e', '#60a5fa', '#fbbf24', '#f87171', '#a78bfa', '#34d399', '#fb923c', '#e879f9', '#38bdf8', '#4ade80', '#facc15'];

interface CustomTooltipProps {
  active?: boolean;
  payload?: { name: string; value: number; payload: ProjectSlice }[];
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  const { name, value } = payload[0].payload;
  const colorIndex = payload[0] as unknown as { index?: number };
  // Recharts doesn't expose the cell index on tooltip payload directly,
  // so we match the name back to the data array index via the fill color.
  const fill = (payload[0] as unknown as { fill?: string }).fill ?? '#7c6bff';
  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-default)',
      borderRadius: 'var(--radius-md)',
      padding: '10px 14px',
      boxShadow: 'var(--shadow-elevated)',
      minWidth: 130,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 4 }}>
        <span style={{ width: 10, height: 10, borderRadius: 3, flexShrink: 0, backgroundColor: fill, display: 'inline-block' }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', wordBreak: 'break-word' }}>
          {name}
        </span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', paddingLeft: 17 }}>
        {value.toLocaleString()} assets
      </div>
    </div>
  );
}

export default function ProjectAssetChart({ data }: Props) {
  const hasData = data.length > 0 && data.some(d => d.value > 0);

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)', padding: 20,
      boxShadow: 'var(--shadow-card)',
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16 }}>
        Asset Distribution
      </div>
      {!hasData ? (
        <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
          No assets yet
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%" cy="50%"
              outerRadius={90} innerRadius={50}
              stroke="var(--bg-base)" strokeWidth={2} paddingAngle={2}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      )}
      {hasData && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 12px', marginTop: 8, justifyContent: 'center' }}>
          {data.map((d, i) => (
            <span key={d.name} style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 5, maxWidth: 160, overflow: 'hidden' }}>
              <span style={{
                width: 8, height: 8, borderRadius: 2, flexShrink: 0, display: 'inline-block',
                backgroundColor: COLORS[i % COLORS.length],
              }} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
