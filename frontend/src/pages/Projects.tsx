// frontend/src/pages/Projects.tsx
import React, { useEffect, useState, useMemo } from 'react';
import { useProjectStore } from '../store/projectStore';
import ProjectGrid from '../components/projects/ProjectGrid';
import NewProjectOverlay from '../components/projects/NewProjectOverlay';
import ProjectSearchBar from '../components/projects/ProjectSearchBar';
import { Plus, CheckSquare, X, Trash2, Radar } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { bulkDeleteProjects } from '../api/projects';
import { enqueueScan } from '../api/scans';

const primaryBtnStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6,
  background: 'var(--accent-primary)',
  color: '#000', border: '1px solid var(--accent-dim)',
  borderRadius: 6, padding: '7px 16px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
  transition: 'all var(--transition-fast)',
};

export default function Projects() {
  const { projects, loadProjects } = useProjectStore();
  const [showNew, setShowNew] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkWorking, setBulkWorking] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [search, setSearch] = useState('');
  const { isAdmin } = useAuth();

  const filtered = useMemo(() => {
    if (!search.trim()) return projects;
    const q = search.toLowerCase();
    return projects.filter((p) =>
      p.title.toLowerCase().includes(q) ||
      p.status.toLowerCase().includes(q) ||
      (p.description && p.description.toLowerCase().includes(q)) ||
      p.root_domains.some((d) => d.toLowerCase().includes(q))
    );
  }, [projects, search]);

  useEffect(() => { loadProjects(); }, []);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selectedIds.size === projects.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(projects.map((p) => p.id)));
    }
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
    setConfirmBulkDelete(false);
  };

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    setBulkWorking(true);
    try {
      await bulkDeleteProjects(Array.from(selectedIds));
      setSelectedIds(new Set());
      setConfirmBulkDelete(false);
      await loadProjects();
    } finally {
      setBulkWorking(false);
    }
  };

  const handleBulkScan = async (type: 'recon' | 'tech' | 'crawl') => {
    if (selectedIds.size === 0) return;
    setBulkWorking(true);
    try {
      for (const pid of selectedIds) {
        await enqueueScan({ project_id: pid, scan_type: type });
      }
      setSelectedIds(new Set());
      exitSelectMode();
    } finally {
      setBulkWorking(false);
    }
  };

  const btnStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 6,
    background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
    border: '1px solid var(--border-default)',
    borderRadius: 6, padding: '7px 14px', fontSize: 12, fontWeight: 500, cursor: 'pointer',
    transition: 'all var(--transition-fast)',
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 22 }}>
        <h2 style={{ color: 'var(--text-primary)', fontSize: 20, fontWeight: 700, margin: 0 }}>Projects</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {isAdmin && projects.length > 0 && (
            <button
              onClick={() => selectMode ? exitSelectMode() : setSelectMode(true)}
              style={{
                ...btnStyle,
                background: selectMode ? 'var(--accent-subtle)' : btnStyle.background,
                borderColor: selectMode ? 'var(--accent-border)' : 'var(--border-default)',
                color: selectMode ? 'var(--accent-primary)' : 'var(--text-secondary)',
              }}
            >
              {selectMode ? <><X size={13} /> Exit Select</> : <><CheckSquare size={13} /> Select</>}
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => setShowNew(true)}
              style={primaryBtnStyle}
            >
              <Plus size={14} /> New Project
            </button>
          )}
        </div>
      </div>

      {/* Bulk actions bar */}
      {selectMode && selectedIds.size > 0 && (
        <div style={{
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-default)', borderRadius: 8,
          padding: '10px 18px', display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14,
          animation: 'fadeIn 150ms ease',
        }}>
          <span style={{
            color: 'var(--accent-primary)', fontSize: 12, fontWeight: 600,
            fontFamily: 'var(--font-mono)',
          }}>
            {selectedIds.size} selected
          </span>
          <button onClick={selectAll} style={btnStyle}>
            {selectedIds.size === projects.length ? 'Deselect All' : 'Select All'}
          </button>
          <div style={{ width: 1, height: 20, background: 'var(--border-default)' }} />
          <button onClick={() => handleBulkScan('recon')} disabled={bulkWorking} style={btnStyle}>
            <Radar size={12} /> Recon All
          </button>
          <button onClick={() => handleBulkScan('tech')} disabled={bulkWorking} style={btnStyle}>
            Tech All
          </button>
          <button onClick={() => handleBulkScan('crawl')} disabled={bulkWorking} style={btnStyle}>
            Crawl All
          </button>
          <div style={{ flex: 1 }} />
          {!confirmBulkDelete ? (
            <button onClick={() => setConfirmBulkDelete(true)} style={{ ...btnStyle, color: 'var(--text-muted)' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; e.currentTarget.style.borderColor = 'var(--status-error-border)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
            >
              <Trash2 size={12} /> Delete
            </button>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>Delete {selectedIds.size}?</span>
              <button onClick={handleBulkDelete} disabled={bulkWorking} style={{
                ...btnStyle, background: 'var(--status-error-bg)', color: 'var(--status-error)',
                borderColor: 'var(--status-error-border)',
              }}>
                {bulkWorking ? 'Deleting...' : 'Confirm'}
              </button>
              <button onClick={() => setConfirmBulkDelete(false)} style={btnStyle}>Cancel</button>
            </div>
          )}
        </div>
      )}

      {projects.length > 0 && (
        <ProjectSearchBar value={search} onChange={setSearch} filtered={filtered} />
      )}
      <ProjectGrid
        projects={filtered}
        selectable={selectMode}
        selectedIds={selectedIds}
        onToggleSelect={toggleSelect}
      />
      <NewProjectOverlay open={showNew} onClose={() => setShowNew(false)} onCreated={loadProjects} />
    </div>
  );
}
