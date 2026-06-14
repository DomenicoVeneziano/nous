// frontend/src/components/projects/BulkActionsMenu.tsx
import React, { useState } from 'react';
import { Trash2 } from 'lucide-react';

interface Props {
  selectedCount: number;
  onRunTech: () => void;
  onRunCrawl: () => void;
  onClear: () => void;
  onDeleteSelected?: () => Promise<void>;
}

export default function BulkActionsMenu({ selectedCount, onRunTech, onRunCrawl, onClear, onDeleteSelected }: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (selectedCount === 0) return null;

  const handleDelete = async () => {
    if (!onDeleteSelected) return;
    setDeleting(true);
    try {
      await onDeleteSelected();
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  };

  const btnStyle: React.CSSProperties = {
    background: 'var(--accent-subtle)', color: 'var(--text-secondary)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)', padding: '5px 12px', fontSize: 12, cursor: 'pointer',
    fontWeight: 500, transition: 'all var(--transition-fast)',
    display: 'flex', alignItems: 'center', gap: 4,
  };

  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-default)', borderRadius: 'var(--radius-lg)',
      padding: '10px 18px', display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14,
      animation: 'fadeIn 150ms ease',
    }}>
      <span style={{
        color: 'var(--accent-primary)', fontSize: 12, fontWeight: 600,
        fontFamily: 'var(--font-mono)',
      }}>
        {selectedCount} selected
      </span>
      <button onClick={onRunTech} style={btnStyle}
        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.borderColor = 'var(--border-emphasis)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
      >Tech Analysis</button>
      <button onClick={onRunCrawl} style={btnStyle}
        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.borderColor = 'var(--border-emphasis)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
      >Crawl</button>
      {onDeleteSelected && (
        <>
          <div style={{ width: 1, height: 20, background: 'var(--border-default)' }} />
          {!confirmDelete ? (
            <button onClick={() => setConfirmDelete(true)} style={{ ...btnStyle, color: 'var(--text-muted)' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; e.currentTarget.style.borderColor = 'var(--status-error-border)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
            >
              <Trash2 size={11} /> Delete
            </button>
          ) : (
            <>
              <button onClick={handleDelete} disabled={deleting} className="btn-danger" style={{ padding: '5px 12px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                {deleting ? 'Deleting...' : `Delete ${selectedCount}`}
              </button>
              <button onClick={() => setConfirmDelete(false)} className="btn-secondary" style={{ padding: '5px 12px', fontSize: 12 }}>
                Cancel
              </button>
            </>
          )}
        </>
      )}
      <div style={{ flex: 1 }} />
      <button onClick={onClear} style={{ ...btnStyle, color: 'var(--text-muted)' }}
        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-secondary)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
      >Clear</button>
    </div>
  );
}
