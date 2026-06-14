// frontend/src/components/projects/ProjectEditOverlay.tsx
import React, { useState, useEffect, useRef } from 'react';
import { updateProject, deleteProject, uploadProjectIcon, deleteProjectIcon, fetchProjectIconUrl } from '../../api/projects';
import type { Project, ProjectUpdate } from '../../types/project';
import { Trash2, Upload, X } from 'lucide-react';

interface Props {
  project: Project;
  open: boolean;
  onClose: () => void;
  onUpdated: () => void;
  onDeleted: () => void;
}


export default function ProjectEditOverlay({ project, open, onClose, onUpdated, onDeleted }: Props) {
  const [title, setTitle] = useState(project.title);
  const [description, setDescription] = useState(project.description || '');
  const [domains, setDomains] = useState(project.root_domains.join('\n'));
  const [iconFile, setIconFile] = useState<File | null>(null);
  const [iconPreview, setIconPreview] = useState<string | null>(null);
  const [removeIcon, setRemoveIcon] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setTitle(project.title);
    setDescription(project.description || '');
    setDomains(project.root_domains.join('\n'));
    setIconFile(null);
    setRemoveIcon(false);
    setConfirmDelete(false);
    setError('');
    setIconPreview(null);
    if (!project.icon) return;
    // Existing icon must be fetched as an authenticated blob (see fetchProjectIconUrl).
    let active = true;
    let objectUrl: string | null = null;
    fetchProjectIconUrl(project.id)
      .then((u) => {
        if (active) { objectUrl = u; setIconPreview(u); }
        else URL.revokeObjectURL(u);
      })
      .catch(() => {});
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [open, project]);

  if (!open) return null;

  const handleIconSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIconFile(file);
    setRemoveIcon(false);
    const reader = new FileReader();
    reader.onload = () => setIconPreview(reader.result as string);
    reader.readAsDataURL(file);
  };

  const clearIcon = () => {
    setIconFile(null);
    setIconPreview(null);
    setRemoveIcon(true);
    if (fileRef.current) fileRef.current.value = '';
  };

  const handleSave = async () => {
    if (!title.trim()) { setError('Title is required'); return; }
    setSaving(true);
    setError('');
    try {
      const payload: ProjectUpdate = {};
      if (title.trim() !== project.title) payload.title = title.trim();
      if ((description.trim() || '') !== (project.description || '')) payload.description = description.trim();
      const newDomains = domains.split('\n').map((d) => d.trim()).filter(Boolean);
      if (JSON.stringify(newDomains) !== JSON.stringify(project.root_domains)) payload.root_domains = newDomains;
      if (Object.keys(payload).length > 0) {
        await updateProject(project.id, payload);
      }
      if (iconFile) {
        await uploadProjectIcon(project.id, iconFile);
      } else if (removeIcon && project.icon) {
        await deleteProjectIcon(project.id);
      }
      onUpdated();
      onClose();
    } catch {
      setError('Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteProject(project.id);
      onDeleted();
    } catch {
      setError('Failed to delete');
      setDeleting(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'var(--bg-elevated)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)', color: 'var(--text-primary)', padding: '9px 12px', fontSize: 13,
    outline: 'none', transition: 'border-color var(--transition-fast)',
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)',
      WebkitBackdropFilter: 'blur(6px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)', borderRadius: 'var(--radius-xl)',
        maxWidth: 540, width: '90%',
        boxShadow: 'var(--shadow-elevated)',
        animation: 'fadeIn 150ms ease',
        overflow: 'hidden', position: 'relative',
      }}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, background: 'linear-gradient(90deg, transparent, rgba(124,107,255,0.3), transparent)' }} />
        <div style={{
          padding: '18px 22px', borderBottom: '1px solid var(--border-subtle)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <h3 style={{ color: 'var(--text-primary)', fontSize: 15, fontWeight: 600, margin: 0 }}>Edit Project</h3>
          {!confirmDelete ? (
            <button onClick={() => setConfirmDelete(true)} style={{
              background: 'transparent', color: 'var(--text-muted)', border: 'none',
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
              fontSize: 12, padding: '4px 8px', borderRadius: 'var(--radius-sm)',
              transition: 'color var(--transition-fast)',
            }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
            >
              <Trash2 size={13} /> Delete
            </button>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>Confirm?</span>
              <button onClick={handleDelete} disabled={deleting} className="btn-danger" style={{ padding: '3px 10px', fontSize: 11 }}>
                {deleting ? 'Deleting...' : 'Yes, Delete'}
              </button>
              <button onClick={() => setConfirmDelete(false)} className="btn-secondary" style={{ padding: '3px 10px', fontSize: 11 }}>No</button>
            </div>
          )}
        </div>

        <div style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 18 }}>
          {error && (
            <div style={{
              background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)',
              borderRadius: 'var(--radius-md)', padding: '8px 12px', fontSize: 12, color: 'var(--status-error)',
              fontFamily: 'var(--font-mono)',
            }}>{error}</div>
          )}

          {/* Icon upload */}
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>
              Project Icon
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              {iconPreview ? (
                <div style={{ position: 'relative' }}>
                  <img
                    src={iconPreview}
                    alt="Icon"
                    style={{
                      width: 48, height: 48, borderRadius: 'var(--radius-lg)', objectFit: 'cover',
                      border: '1px solid var(--border-default)',
                    }}
                  />
                  <button
                    onClick={clearIcon}
                    style={{
                      position: 'absolute', top: -6, right: -6,
                      width: 18, height: 18, borderRadius: '50%',
                      background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
                      color: 'var(--text-secondary)', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      padding: 0,
                    }}
                  >
                    <X size={10} />
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => fileRef.current?.click()}
                  style={{
                    width: 48, height: 48, borderRadius: 'var(--radius-lg)',
                    background: 'var(--bg-elevated)', border: '1px dashed var(--border-default)',
                    color: 'var(--text-muted)', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--border-emphasis)'; e.currentTarget.style.color = 'var(--text-secondary)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border-default)'; e.currentTarget.style.color = 'var(--text-muted)'; }}
                >
                  <Upload size={18} />
                </button>
              )}
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                onChange={handleIconSelect}
                style={{ display: 'none' }}
              />
              {iconPreview && (
                <button
                  onClick={() => fileRef.current?.click()}
                  className="btn-secondary"
                  style={{ padding: '4px 10px', fontSize: 11 }}
                >
                  Change
                </button>
              )}
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>PNG, JPG, GIF, WebP, SVG — max 2MB</span>
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>Title</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle} />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>Description</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} style={inputStyle} placeholder="Optional" />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>
              Scope (one per line)
            </label>
            <textarea
              value={domains}
              onChange={(e) => setDomains(e.target.value)}
              rows={5}
              style={{
                ...inputStyle, fontFamily: 'var(--font-mono)', fontSize: 12,
                resize: 'vertical', lineHeight: 1.6,
              }}
            />
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.5 }}>
              Wildcard domains (*.example.com) define recon scope. Specific hostnames are added as assets automatically.
            </div>
          </div>
        </div>

        <div style={{
          padding: '14px 22px', borderTop: '1px solid var(--border-subtle)',
          display: 'flex', justifyContent: 'flex-end', gap: 8,
        }}>
          <button onClick={onClose} className="btn-secondary">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="btn-primary">
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
