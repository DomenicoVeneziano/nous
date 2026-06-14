// frontend/src/components/projects/ProjectSearchBar.tsx
import React, { useCallback } from 'react';
import { Search, Download } from 'lucide-react';
import type { Project } from '../../types/project';
import SearchHelpButton from '../shared/SearchHelpButton';

interface Props {
  value: string;
  onChange: (value: string) => void;
  filtered: Project[];
}

const PROJECT_SEARCH_SECTIONS = [
  {
    heading: 'What it searches',
    rows: [
      { label: 'name',        desc: 'Project title (substring, case-insensitive)' },
      { label: 'domain',      desc: 'Root domains defined on the project' },
      { label: 'status',      desc: 'to_scan, scanning, or scanned' },
    ],
  },
  {
    heading: 'How it works',
    rows: [
      { label: 'plain text',  desc: 'Any text is matched against all three fields simultaneously' },
      { label: 'sisal',       desc: 'Shows all projects whose name or domain contains "sisal"' },
      { label: 'scanned',     desc: 'Shows all projects with status "scanned"' },
    ],
  },
];

const linkStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  background: 'transparent', color: 'var(--text-secondary)',
  border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-sm)', padding: '5px 10px', fontSize: 11,
  textDecoration: 'none', fontFamily: 'var(--font-mono)',
  fontWeight: 500, letterSpacing: '0.03em', cursor: 'pointer',
  transition: 'all var(--transition-fast)',
};

function downloadBlob(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ProjectSearchBar({ value, onChange, filtered }: Props) {
  const exportJSON = useCallback(() => {
    downloadBlob(JSON.stringify(filtered, null, 2), 'projects.json', 'application/json');
  }, [filtered]);

  const exportCSV = useCallback(() => {
    const headers = ['id', 'title', 'description', 'root_domains', 'status', 'asset_count', 'tech_count', 'last_scan_date'];
    const rows = filtered.map((p) =>
      headers.map((h) => {
        const val = p[h as keyof Project];
        if (Array.isArray(val)) return `"${val.join(', ')}"`;
        if (val === null || val === undefined) return '';
        return `"${String(val).replace(/"/g, '""')}"`;
      }).join(',')
    );
    downloadBlob([headers.join(','), ...rows].join('\n'), 'projects.csv', 'text/csv');
  }, [filtered]);

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14 }}>
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', gap: 8,
        background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-md)', padding: '8px 12px',
        transition: 'border-color var(--transition-fast)',
      }}>
        <Search size={14} color="var(--text-muted)" />
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Filter projects by name, domain, or status..."
          style={{
            flex: 1, background: 'transparent', border: 'none', outline: 'none',
            color: 'var(--text-primary)', fontSize: 12, fontFamily: 'var(--font-mono)',
          }}
        />
        <SearchHelpButton sections={PROJECT_SEARCH_SECTIONS} />
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <button onClick={exportJSON} style={linkStyle}>
          <Download size={11} /> JSON
        </button>
        <button onClick={exportCSV} style={linkStyle}>
          <Download size={11} /> CSV
        </button>
      </div>
    </div>
  );
}
