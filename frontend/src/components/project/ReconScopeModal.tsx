// frontend/src/components/project/ReconScopeModal.tsx
import React, { useState } from 'react';
import { Modal } from '../shared/ConfirmModal';

interface Props {
  domains: string[];
  onConfirm: (selected: string[]) => void;
  onClose: () => void;
}

export default function ReconScopeModal({ domains, onConfirm, onClose }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set(domains));

  const allSelected = selected.size === domains.length;

  const toggle = (domain: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain); else next.add(domain);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(domains));
  };

  const handleConfirm = () => {
    onConfirm(Array.from(selected));
  };

  const domainRowStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '7px 0',
    borderBottom: '1px solid var(--border-subtle)',
    cursor: 'pointer',
  };

  return (
    <Modal
      open
      title="Select Scopes to Recon"
      onClose={onClose}
      maxWidth={480}
      footer={
        <>
          <button
            onClick={onClose}
            className="btn-secondary"
            style={{ padding: '8px 18px', fontSize: 13 }}
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={selected.size === 0}
            className="btn-primary"
            style={{
              padding: '8px 18px', fontSize: 13,
              opacity: selected.size === 0 ? 0.45 : 1,
              cursor: selected.size === 0 ? 'not-allowed' : 'pointer',
            }}
          >
            Launch Recon{selected.size < domains.length ? ` (${selected.size})` : ''}
          </button>
        </>
      }
    >
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
        Choose which root domains to include in this recon run.
      </div>

      {/* Select all toggle */}
      <div
        style={{ ...domainRowStyle, borderBottom: '1px solid var(--border-default)', marginBottom: 4, paddingBottom: 10 }}
        onClick={toggleAll}
      >
        <input
          type="checkbox"
          checked={allSelected}
          onChange={toggleAll}
          onClick={(e) => e.stopPropagation()}
          style={{ cursor: 'pointer', accentColor: 'var(--accent-primary)', width: 14, height: 14 }}
        />
        <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>
          {allSelected ? 'Deselect all' : 'Select all'}
        </span>
      </div>

      {/* Domain list */}
      <div style={{ maxHeight: 260, overflowY: 'auto' }}>
        {domains.map((domain) => (
          <div key={domain} style={domainRowStyle} onClick={() => toggle(domain)}>
            <input
              type="checkbox"
              checked={selected.has(domain)}
              onChange={() => toggle(domain)}
              onClick={(e) => e.stopPropagation()}
              style={{ cursor: 'pointer', accentColor: 'var(--accent-primary)', width: 14, height: 14 }}
            />
            <span style={{
              fontSize: 12, fontFamily: 'var(--font-mono)',
              color: selected.has(domain) ? 'var(--text-primary)' : 'var(--text-muted)',
            }}>
              {domain}
            </span>
          </div>
        ))}
      </div>
    </Modal>
  );
}
