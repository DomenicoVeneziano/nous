// frontend/src/components/shared/ExportButton.tsx
import React from 'react';
import { Download } from 'lucide-react';
import { exportAssets } from '../../api/settings';

interface Props {
  query: string;
  projectId?: string;
}

const btnStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  background: 'transparent', color: 'var(--text-secondary)',
  border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-sm)', padding: '5px 10px', fontSize: 11,
  textDecoration: 'none', fontFamily: 'var(--font-mono)',
  fontWeight: 500, letterSpacing: '0.03em',
  transition: 'all var(--transition-fast)',
  cursor: 'pointer',
};

export default function ExportButton({ query, projectId }: Props) {
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      <button style={btnStyle} onClick={() => exportAssets(query, 'json', projectId)}>
        <Download size={11} /> JSON
      </button>
      <button style={btnStyle} onClick={() => exportAssets(query, 'csv', projectId)}>
        <Download size={11} /> CSV
      </button>
    </div>
  );
}
