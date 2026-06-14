// frontend/src/components/dashboard/TechHistogram.tsx
import React from 'react';
import {
  BarChart, Bar, Cell, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts';

interface Props {
  data: { name: string; count: number }[];
}

const tooltipStyle: React.CSSProperties = {
  backgroundColor: 'var(--bg-elevated)',
  border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-md)',
  color: 'var(--text-primary)',
  fontSize: 12,
  fontFamily: 'var(--font-mono)',
  boxShadow: 'var(--shadow-elevated)',
  padding: '8px 12px',
};

// Stable color per tech name so the bar color doesn't shift on re-renders
const PALETTE = [
  '#7c6bff', '#3ecf8e', '#60a5fa', '#fbbf24',
  '#f87171', '#a78bfa', '#34d399', '#fb923c',
  '#e879f9', '#38bdf8', '#4ade80', '#facc15',
];
function techColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
  return PALETTE[Math.abs(h) % PALETTE.length];
}

export default function TechHistogram({ data }: Props) {
  // Each bar row is 28px tall; minimum chart height is 220px
  const chartHeight = Math.max(220, data.length * 28);
  // Left margin wide enough for longest tech label (cap at 160px)
  const maxLabelLen = data.reduce((m, d) => Math.max(m, d.name.length), 0);
  const leftMargin = Math.min(160, Math.max(80, maxLabelLen * 6));

  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)',
      padding: 20,
      boxShadow: 'var(--shadow-card)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{
        fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16,
        flexShrink: 0,
      }}>
        Technology Distribution
      </div>

      {data.length === 0 ? (
        <div style={{
          height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-mono)',
        }}>
          No technology data yet
        </div>
      ) : (
        <div style={{ overflowY: 'auto', maxHeight: 260, flexShrink: 0 }}>
          {/* Width must be explicit (not %) so the chart scrolls rather than squishes */}
          <BarChart
            layout="vertical"
            width={500}
            height={chartHeight}
            data={data}
            margin={{ top: 0, right: 16, bottom: 0, left: leftMargin }}
            barCategoryGap="20%"
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--border-subtle)"
              horizontal={false}
            />
            <XAxis
              type="number"
              allowDecimals={false}
              tick={{ fill: 'var(--text-muted)', fontSize: 10, fontFamily: 'var(--font-mono)' }}
              axisLine={{ stroke: 'var(--border-subtle)' }}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={leftMargin}
              tick={{ fill: 'var(--text-secondary)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={tooltipStyle}
              itemStyle={{ color: 'var(--text-primary)' }}
              labelStyle={{ color: 'var(--text-secondary)' }}
              cursor={{ fill: 'rgba(124,107,255,0.05)' }}
              formatter={(value: number) => [value, 'assets']}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {data.map((d) => (
                <Cell key={d.name} fill={techColor(d.name)} />
              ))}
            </Bar>
          </BarChart>
        </div>
      )}
    </div>
  );
}
