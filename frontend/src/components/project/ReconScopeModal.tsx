// frontend/src/components/project/ReconScopeModal.tsx
import React, { useState } from 'react';
import { Modal } from '../shared/ConfirmModal';

/** Mirrors the backend `MAX_ARCHIVE_HOSTS`: every non-root entry is a long
 *  sequential archive run on the single-threaded engine. Roots are not capped. */
export const MAX_RECON_SCOPE = 500;

interface Props {
  domains: string[];
  hosts: string[];
  onConfirm: (selected: string[]) => void;
  onClose: () => void;
}

export default function ReconScopeModal({ domains, hosts, onConfirm, onClose }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set(domains));

  const all = Array.from(new Set([...domains, ...hosts]));
  // `hosts` can change while the modal is open, so count only entries still offered.
  const chosen = all.filter((d) => selected.has(d));
  const allSelected = chosen.length === all.length;
  const rootSet = new Set(domains);
  const chosenHosts = chosen.filter((d) => !rootSet.has(d)).length;
  const overCap = chosenHosts > MAX_RECON_SCOPE;
  const disabled = chosen.length === 0 || overCap;

  const toggle = (domain: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain); else next.add(domain);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(all));
  };

  const handleConfirm = () => {
    if (disabled) return;
    onConfirm(chosen);
  };

  const domainRowStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '7px 0',
    borderBottom: '1px solid var(--border-subtle)',
    cursor: 'pointer',
  };

  const sectionLabelStyle: React.CSSProperties = {
    fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
    textTransform: 'uppercase', letterSpacing: '0.04em', padding: '6px 0 2px',
  };

  const renderRow = (domain: string) => (
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
  );

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
            disabled={disabled}
            className="btn-primary"
            style={{
              padding: '8px 18px', fontSize: 13,
              opacity: disabled ? 0.45 : 1,
              cursor: disabled ? 'not-allowed' : 'pointer',
            }}
          >
            Launch Recon{chosen.length < all.length ? ` (${chosen.length})` : ''}
          </button>
        </>
      }
    >
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
        Choose which root domains and scope hosts to include in this recon run.
      </div>

      {overCap && (
        <div style={{ fontSize: 12, color: 'var(--status-error)', marginBottom: 10 }}>
          At most {MAX_RECON_SCOPE} hosts per recon run; {chosenHosts} selected.
        </div>
      )}

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
        <div style={sectionLabelStyle}>Root domains: full recon</div>
        {domains.map(renderRow)}
        {hosts.length > 0 && (
          <>
            <div style={{ ...sectionLabelStyle, marginTop: 12 }}>Scope hosts: archived URLs only</div>
            {hosts.filter((h) => !rootSet.has(h)).map(renderRow)}
          </>
        )}
      </div>
    </Modal>
  );
}
