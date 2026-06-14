// frontend/src/components/settings/ApiKeyManagement.tsx
import React, { useEffect, useState } from 'react';
import { Pencil, Check, X, Copy, KeyRound } from 'lucide-react';
import type { ApiKey, ApiKeyCreated } from '../../types/apiKey';
import { fetchApiKeys, createApiKey, renameApiKey, deleteApiKey } from '../../api/apiKeys';
import { useAuth } from '../../hooks/useAuth';
import ConfirmModal from '../shared/ConfirmModal';

const primaryBtnStyle: React.CSSProperties = {
  background: 'var(--accent-primary)',
  color: 'var(--bg-base)',
  border: '1px solid var(--accent-dim)',
  borderRadius: 6, padding: '7px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
  transition: 'all var(--transition-fast)', whiteSpace: 'nowrap',
};

const inputStyle: React.CSSProperties = {
  background: 'var(--bg-base)', border: '1px solid var(--border-default)',
  borderRadius: 6, color: 'var(--text-primary)', padding: '8px 12px', fontSize: 13,
  outline: 'none', transition: 'border-color var(--transition-fast)',
};

const thStyle: React.CSSProperties = {
  background: 'var(--bg-elevated)', color: 'var(--text-muted)',
  fontSize: 11, fontWeight: 600,
  textTransform: 'uppercase', letterSpacing: '0.06em',
  padding: '12px 16px', textAlign: 'left',
  borderBottom: '1px solid var(--border-default)',
};

const tdStyle: React.CSSProperties = {
  padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', fontSize: 14,
};

function typeBadgeStyle(key_type: 'edit' | 'view'): React.CSSProperties {
  return {
    fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 600,
    letterSpacing: '0.06em', padding: '4px 10px', borderRadius: 4,
    background: key_type === 'edit' ? 'var(--accent-subtle)' : 'var(--status-muted-bg)',
    color:      key_type === 'edit' ? 'var(--accent-primary)' : 'var(--text-muted)',
    border:     key_type === 'edit' ? '1px solid var(--accent-border)' : '1px solid var(--status-muted-border)',
  };
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export default function ApiKeyManagement() {
  const { isAdmin } = useAuth();

  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<'edit' | 'view'>('view');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  const [revealKey, setRevealKey] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editError, setEditError] = useState('');

  const load = () => fetchApiKeys().then(setKeys).catch(() => {});

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    setCreateError('');
    try {
      const created = await createApiKey({ name: newName.trim(), key_type: newType });
      setRevealKey(created);
      setNewName('');
      setNewType('view');
      setShowCreate(false);
      load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setCreateError(msg || 'Failed to create key');
    } finally {
      setCreating(false);
    }
  };

  const handleCopy = () => {
    if (!revealKey) return;
    navigator.clipboard.writeText(revealKey.full_key).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    await deleteApiKey(deleteId);
    setDeleteId(null);
    load();
  };

  const startEdit = (key: ApiKey) => {
    setEditingId(key.id);
    setEditName(key.name);
    setEditError('');
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditName('');
    setEditError('');
  };

  const saveEdit = async (keyId: string) => {
    if (!editName.trim()) return;
    try {
      await renameApiKey(keyId, { name: editName.trim() });
      cancelEdit();
      load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setEditError(msg || 'Failed to rename');
    }
  };

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, overflow: 'hidden',
      boxShadow: 'var(--shadow-card), inset 0 1px 0 rgba(255,255,255,0.02)',
    }}>
      {/* Header */}
      <div style={{
        padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div>
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>API Keys</span>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
            Use API keys to authenticate programmatic access.{' '}
            {isAdmin
              ? 'Edit keys have full access; view keys are read-only.'
              : 'As a viewer, you can create read-only keys.'}
          </p>
        </div>
        <button onClick={() => { setShowCreate(!showCreate); setCreateError(''); }} style={primaryBtnStyle}>
          New Key
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)',
          background: 'var(--bg-elevated)', display: 'flex', flexDirection: 'column', gap: 10,
        }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Key name (e.g. CI pipeline)"
              style={{ ...inputStyle, flex: 1, minWidth: 180 }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
            />
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value as 'edit' | 'view')}
              style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }}
            >
              {isAdmin && <option value="edit">Edit (full access)</option>}
              <option value="view">View (read-only)</option>
            </select>
            <button onClick={handleCreate} disabled={creating || !newName.trim()} style={{
              ...primaryBtnStyle,
              opacity: creating || !newName.trim() ? 0.6 : 1,
              cursor: creating || !newName.trim() ? 'not-allowed' : 'pointer',
            }}>
              {creating ? 'Creating…' : 'Create'}
            </button>
          </div>
          {createError && (
            <div style={{ fontSize: 12, color: 'var(--status-error)', fontFamily: 'var(--font-mono)' }}>
              {createError}
            </div>
          )}
        </div>
      )}

      {/* Key table */}
      {keys.length === 0 && !showCreate ? (
        <div style={{
          padding: '40px 20px', textAlign: 'center',
          color: 'var(--text-muted)', fontSize: 13,
        }}>
          <KeyRound size={28} style={{ marginBottom: 10, opacity: 0.4 }} />
          <p style={{ margin: 0 }}>No API keys yet. Create one to get started.</p>
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={thStyle}>Name</th>
              <th style={thStyle}>Type</th>
              <th style={thStyle}>Prefix</th>
              <th style={thStyle}>Created</th>
              <th style={thStyle}>Last Used</th>
              <th style={thStyle}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k, i) => {
              const isEditing = editingId === k.id;
              return (
                <tr
                  key={k.id}
                  style={{
                    background: isEditing ? 'var(--bg-selected)' : (i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)'),
                    transition: 'background var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { if (!isEditing) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                  onMouseLeave={(e) => { if (!isEditing) e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)'; }}
                >
                  <td style={tdStyle}>
                    {isEditing ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <input
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          style={{ ...inputStyle, fontSize: 13 }}
                          onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(k.id); if (e.key === 'Escape') cancelEdit(); }}
                          autoFocus
                        />
                        {editError && (
                          <div style={{ fontSize: 12, color: 'var(--status-error)', fontFamily: 'var(--font-mono)' }}>
                            {editError}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{k.name}</span>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <span style={typeBadgeStyle(k.key_type)}>
                      {k.key_type.toUpperCase()}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <code style={{
                      fontFamily: 'var(--font-mono)', fontSize: 12,
                      color: 'var(--text-code)', background: 'var(--bg-elevated)',
                      padding: '2px 6px', borderRadius: 4,
                    }}>
                      {k.key_prefix}…
                    </code>
                  </td>
                  <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 13 }}>
                    {formatDate(k.created_at)}
                  </td>
                  <td style={{ ...tdStyle, color: 'var(--text-muted)', fontSize: 13 }}>
                    {formatDate(k.last_used_at)}
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      {isEditing ? (
                        <>
                          <button onClick={() => saveEdit(k.id)} title="Save" style={{
                            background: 'var(--status-success-bg)', color: 'var(--status-success)',
                            border: '1px solid var(--status-success-border)',
                            borderRadius: 5, padding: '5px 8px', cursor: 'pointer',
                            display: 'flex', alignItems: 'center', transition: 'all var(--transition-fast)',
                          }}>
                            <Check size={13} />
                          </button>
                          <button onClick={cancelEdit} title="Cancel" style={{
                            background: 'var(--status-muted-bg)', color: '#5c5c5c',
                            border: '1px solid var(--status-muted-border)',
                            borderRadius: 5, padding: '5px 8px', cursor: 'pointer',
                            display: 'flex', alignItems: 'center', transition: 'all var(--transition-fast)',
                          }}>
                            <X size={13} />
                          </button>
                        </>
                      ) : (
                        <button onClick={() => startEdit(k)} title="Rename" style={{
                          background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
                          border: '1px solid var(--border-default)',
                          borderRadius: 5, padding: '5px 8px', cursor: 'pointer',
                          display: 'flex', alignItems: 'center', transition: 'all var(--transition-fast)',
                        }}
                          onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.2)'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.filter = 'brightness(1)'; }}
                        >
                          <Pencil size={13} />
                        </button>
                      )}
                      <button onClick={() => setDeleteId(k.id)} style={{
                        background: 'var(--status-error-bg)', color: 'var(--status-error)',
                        border: '1px solid var(--status-error-border)',
                        borderRadius: 5, padding: '5px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                        fontFamily: 'var(--font-mono)', letterSpacing: '0.04em',
                        transition: 'all var(--transition-fast)',
                      }}
                        onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.2)'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.filter = 'brightness(1)'; }}
                      >
                        Revoke
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Key reveal modal — shown exactly once after creation */}
      {revealKey && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(4px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
            borderRadius: 10, padding: '28px 32px', maxWidth: 560, width: '90%',
            boxShadow: 'var(--shadow-elevated)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <KeyRound size={18} color="var(--accent-primary)" />
              <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>
                API Key Created
              </span>
              <span style={{ ...typeBadgeStyle(revealKey.key_type), marginLeft: 4 }}>
                {revealKey.key_type.toUpperCase()}
              </span>
            </div>
            <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              Copy this key now — it will not be shown again. Store it somewhere safe.
            </p>
            <div style={{
              background: 'var(--bg-base)', border: '1px solid var(--border-default)',
              borderRadius: 6, padding: '12px 14px', marginBottom: 16,
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <code style={{
                fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-code)',
                wordBreak: 'break-all', flex: 1,
              }}>
                {revealKey.full_key}
              </code>
              <button onClick={handleCopy} title="Copy to clipboard" style={{
                background: copied ? 'var(--status-success-bg)' : 'var(--bg-elevated)',
                color: copied ? 'var(--status-success)' : 'var(--text-secondary)',
                border: copied ? '1px solid var(--status-success-border)' : '1px solid var(--border-default)',
                borderRadius: 5, padding: '6px 10px', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 5,
                fontSize: 12, fontWeight: 600, transition: 'all var(--transition-fast)',
                flexShrink: 0,
              }}>
                <Copy size={12} />
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setRevealKey(null); setCopied(false); }}
                style={primaryBtnStyle}
              >
                I have saved this key
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        open={!!deleteId}
        title="Revoke API Key"
        message="This key will be permanently deleted and any scripts using it will stop working."
        onConfirm={handleDelete}
        onCancel={() => setDeleteId(null)}
        destructive
      />
    </div>
  );
}
