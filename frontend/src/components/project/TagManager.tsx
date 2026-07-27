// frontend/src/components/project/TagManager.tsx
import React, { useCallback, useEffect, useState } from 'react';
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react';
import type { TagWithCount } from '../../types/tag';
import { createTag, deleteTag, fetchTags, updateTag } from '../../api/tags';
import TagChip from '../shared/TagChip';

interface Props {
  projectId: string;
  open: boolean;
  onClose: () => void;
  /** Fired after any change, so the asset list can pick up renames/deletions. */
  onChanged?: () => void;
}

function errorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

const DEFAULT_COLOR = '#a3a3a3';

/**
 * Project-level tag CRUD.
 *
 * Discovery-source tags are listed for reference but not editable — they record
 * how assets were found, and the API refuses to rename or delete them whatever
 * this dialog renders.
 */
export default function TagManager({ projectId, open, onClose, onChanged }: Props) {
  const [tags, setTags] = useState<TagWithCount[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState(DEFAULT_COLOR);
  const [useColor, setUseColor] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editColor, setEditColor] = useState(DEFAULT_COLOR);
  const [editUseColor, setEditUseColor] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setTags(await fetchTags(projectId));
    } catch (err) {
      setError(errorMessage(err, 'Could not load tags'));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { if (open) load(); }, [open, load]);

  if (!open) return null;

  const run = async (fn: () => Promise<unknown>, fallback: string) => {
    setBusy(true);
    setError('');
    try {
      await fn();
      await load();
      onChanged?.();
      return true;
    } catch (err) {
      setError(errorMessage(err, fallback));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    const ok = await run(
      () => createTag(projectId, { name: newName.trim(), color: useColor ? newColor : null }),
      'Could not create tag',
    );
    if (ok) { setNewName(''); setUseColor(false); setNewColor(DEFAULT_COLOR); }
  };

  const startEdit = (tag: TagWithCount) => {
    setEditingId(tag.id);
    setEditName(tag.name);
    setEditUseColor(tag.color != null);
    setEditColor(tag.color ?? DEFAULT_COLOR);
    setConfirmId(null);
  };

  const handleSaveEdit = async (tagId: string) => {
    if (!editName.trim()) return;
    const ok = await run(
      () => updateTag(projectId, tagId, {
        name: editName.trim(),
        color: editUseColor ? editColor : null,
      }),
      'Could not update tag',
    );
    if (ok) setEditingId(null);
  };

  const handleDelete = (tagId: string) =>
    run(() => deleteTag(projectId, tagId), 'Could not delete tag')
      .then(() => setConfirmId(null));

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-void)', border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
    padding: '5px 8px', fontSize: 12, fontFamily: 'var(--font-mono)', outline: 'none',
  };

  const iconBtn: React.CSSProperties = {
    background: 'transparent', border: 'none', cursor: 'pointer',
    color: 'var(--text-muted)', padding: 3, display: 'flex', alignItems: 'center',
  };

  const systemTags = tags.filter((t) => t.is_system);
  const userTags = tags.filter((t) => !t.is_system);

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 950, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        animation: 'fadeIn 150ms ease',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-elevated)',
          width: 'min(560px, 92vw)', maxHeight: '80vh', overflow: 'auto', padding: 20,
        }}
      >
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16,
        }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>Manage Tags</h3>
          <button onClick={onClose} style={iconBtn} aria-label="Close"><X size={16} /></button>
        </div>

        {error && (
          <div style={{
            background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)',
            borderRadius: 'var(--radius-md)', padding: '6px 10px', fontSize: 11,
            color: 'var(--status-error)', fontFamily: 'var(--font-mono)', marginBottom: 12,
          }}>{error}</div>
        )}

        <form onSubmit={handleCreate} style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 18 }}>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New tag name"
            maxLength={40}
            disabled={busy}
            style={{ ...inputStyle, flex: 1 }}
          />
          <label style={{
            display: 'flex', alignItems: 'center', gap: 4, fontSize: 10,
            color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', cursor: 'pointer',
          }}>
            <input type="checkbox" checked={useColor} onChange={(e) => setUseColor(e.target.checked)} />
            Colour
          </label>
          {useColor && (
            <input
              type="color"
              value={newColor}
              onChange={(e) => setNewColor(e.target.value)}
              style={{ width: 30, height: 26, background: 'transparent', border: 'none', cursor: 'pointer' }}
            />
          )}
          <button
            type="submit"
            disabled={busy || !newName.trim()}
            className="btn-secondary"
            style={{
              padding: '5px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4,
              opacity: busy || !newName.trim() ? 0.5 : 1,
            }}
          >
            <Plus size={11} /> Create
          </button>
        </form>

        {loading && (
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div>
        )}

        {!loading && userTags.length === 0 && (
          <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 18 }}>
            No tags yet. Create one above, or add one directly from an asset.
          </div>
        )}

        {userTags.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 20 }}>
            {userTags.map((tag) => (
              <div
                key={tag.id}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '6px 8px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)',
                }}
              >
                {editingId === tag.id ? (
                  <>
                    <input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      maxLength={40}
                      style={{ ...inputStyle, flex: 1 }}
                    />
                    <label style={{
                      display: 'flex', alignItems: 'center', gap: 4, fontSize: 10,
                      color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', cursor: 'pointer',
                    }}>
                      <input
                        type="checkbox"
                        checked={editUseColor}
                        onChange={(e) => setEditUseColor(e.target.checked)}
                      />
                      Colour
                    </label>
                    {editUseColor && (
                      <input
                        type="color"
                        value={editColor}
                        onChange={(e) => setEditColor(e.target.value)}
                        style={{ width: 30, height: 26, background: 'transparent', border: 'none', cursor: 'pointer' }}
                      />
                    )}
                    <button
                      onClick={() => handleSaveEdit(tag.id)}
                      disabled={busy || !editName.trim()}
                      style={{ ...iconBtn, opacity: busy || !editName.trim() ? 0.5 : 1 }}
                      aria-label="Save"
                    >
                      <Check size={13} />
                    </button>
                    <button onClick={() => setEditingId(null)} style={iconBtn} aria-label="Cancel">
                      <X size={13} />
                    </button>
                  </>
                ) : (
                  <>
                    <TagChip label={tag.name} variant="user" color={tag.color} />
                    <span style={{
                      flex: 1, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
                    }}>
                      {tag.asset_count} asset{tag.asset_count === 1 ? '' : 's'}
                    </span>
                    {confirmId === tag.id ? (
                      <>
                        <button
                          onClick={() => handleDelete(tag.id)}
                          disabled={busy}
                          className="btn-danger"
                          style={{ padding: '3px 8px', fontSize: 10 }}
                        >
                          Confirm
                        </button>
                        <button onClick={() => setConfirmId(null)} style={iconBtn} aria-label="Cancel delete">
                          <X size={13} />
                        </button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => startEdit(tag)} style={iconBtn} aria-label={`Edit ${tag.name}`}>
                          <Pencil size={12} />
                        </button>
                        <button onClick={() => setConfirmId(tag.id)} style={iconBtn} aria-label={`Delete ${tag.name}`}>
                          <Trash2 size={12} />
                        </button>
                      </>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        )}

        {systemTags.length > 0 && (
          <div>
            <div style={{
              fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em',
              color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600,
            }}>
              Discovery sources · read-only
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {systemTags.map((tag) => (
                <span key={tag.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <TagChip label={tag.name} variant="system" />
                  <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {tag.asset_count}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
