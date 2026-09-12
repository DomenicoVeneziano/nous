// frontend/src/components/projects/ProjectOverlay.tsx
import React, { useState, useEffect, useRef } from 'react';
import {
  createProject, updateProject, deleteProject,
  uploadProjectIcon, deleteProjectIcon, fetchProjectIconUrl,
} from '../../api/projects';
import type { Project, ProjectCreate, ProjectUpdate, ScanPhase, ScheduleUnit } from '../../types/project';
import { Trash2, Upload, X } from 'lucide-react';
import ScheduleFields, { isScheduleValid } from './ScheduleFields';

interface Props {
  open: boolean;
  onClose: () => void;
  /** Absent for a creation; present to edit that project in place. */
  project?: Project;
  onSaved: () => void;
  /** Only meaningful alongside `project` — the delete control renders with it. */
  onDeleted?: () => void;
}

/** The shared `.input` class sits on the page background with roomier padding;
 *  inside the overlay card the fields are raised and tighter. */
const fieldStyle: React.CSSProperties = { background: 'var(--bg-elevated)', padding: '9px 12px' };

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6,
};

export default function ProjectOverlay({ open, onClose, project, onSaved, onDeleted }: Props) {
  const [title, setTitle] = useState(project?.title ?? '');
  const [description, setDescription] = useState(project?.description ?? '');
  const [domains, setDomains] = useState(project?.root_domains.join('\n') ?? '');
  const [iconFile, setIconFile] = useState<File | null>(null);
  const [iconPreview, setIconPreview] = useState<string | null>(null);
  const [removeIcon, setRemoveIcon] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState('');
  const [scheduleEnabled, setScheduleEnabled] = useState(project?.schedule_enabled ?? false);
  const [intervalValue, setIntervalValue] = useState(project?.schedule_interval_value ?? 7);
  const [intervalUnit, setIntervalUnit] = useState<ScheduleUnit>(project?.schedule_interval_unit ?? 'days');
  const [phases, setPhases] = useState<ScanPhase[]>(project?.schedule_phases ?? ['recon']);
  const fileRef = useRef<HTMLInputElement>(null);

  const scheduleValid = isScheduleValid({ enabled: scheduleEnabled, intervalValue, intervalUnit, phases });

  // Editing re-seats the form on the project every time the overlay opens. A
  // creation deliberately keeps whatever was typed, so a rejected attempt can be
  // corrected rather than retyped.
  useEffect(() => {
    if (!open || !project) return;
    setTitle(project.title);
    setDescription(project.description || '');
    setDomains(project.root_domains.join('\n'));
    // A disabled schedule carries nulls; fall back to the same defaults a new
    // project offers so the fields are usable the moment it is enabled.
    setScheduleEnabled(project.schedule_enabled);
    setIntervalValue(project.schedule_interval_value ?? 7);
    setIntervalUnit(project.schedule_interval_unit ?? 'days');
    setPhases(project.schedule_phases ?? ['recon']);
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

  // Escape dismisses the overlay the same way a backdrop click does, matching
  // the shared Modal. Bound only while open, so a closed overlay holds nothing.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setError(''); onClose(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

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

  // The overlay stays mounted between openings, so a failed attempt would
  // otherwise greet the operator with its old banner the next time around.
  const handleClose = () => {
    setError('');
    onClose();
  };

  const handleCreate = async () => {
    const payload: ProjectCreate = {
      title: title.trim(),
      description: description.trim() || undefined,
      root_domains: domains.split('\n').map((d) => d.trim()).filter(Boolean),
    };
    // The interval and phases only mean anything alongside an enabled
    // schedule, so they stay out of the payload otherwise.
    if (scheduleEnabled) {
      payload.schedule_enabled = true;
      payload.schedule_interval_value = intervalValue;
      payload.schedule_interval_unit = intervalUnit;
      payload.schedule_phases = phases;
    }
    const created = await createProject(payload);
    if (iconFile) {
      try { await uploadProjectIcon(created.id, iconFile); } catch { /* non-fatal */ }
    }
    setTitle('');
    setDescription('');
    setDomains('');
    setScheduleEnabled(false);
    setIntervalValue(7);
    setIntervalUnit('days');
    setPhases(['recon']);
    clearIcon();
    setRemoveIcon(false);
  };

  const handleUpdate = async (target: Project) => {
    const payload: ProjectUpdate = {};
    if (title.trim() !== target.title) payload.title = title.trim();
    if ((description.trim() || '') !== (target.description || '')) payload.description = description.trim();
    const newDomains = domains.split('\n').map((d) => d.trim()).filter(Boolean);
    if (JSON.stringify(newDomains) !== JSON.stringify(target.root_domains)) payload.root_domains = newDomains;
    // While the schedule is off the interval fields hold placeholder defaults
    // rather than the project's nulls, so they only count as a change when it is on.
    const scheduleChanged =
      scheduleEnabled !== target.schedule_enabled ||
      (scheduleEnabled && (
        intervalValue !== target.schedule_interval_value ||
        intervalUnit !== target.schedule_interval_unit ||
        JSON.stringify(phases) !== JSON.stringify(target.schedule_phases)
      ));
    if (scheduleChanged) {
      payload.schedule_enabled = scheduleEnabled;
      // An enabled schedule is only ever accepted as a complete set, so the
      // interval and phases ride along with every change that keeps it on.
      if (scheduleEnabled) {
        payload.schedule_interval_value = intervalValue;
        payload.schedule_interval_unit = intervalUnit;
        payload.schedule_phases = phases;
      }
    }
    if (Object.keys(payload).length > 0) {
      await updateProject(target.id, payload);
    }
    if (iconFile) {
      await uploadProjectIcon(target.id, iconFile);
    } else if (removeIcon && target.icon) {
      await deleteProjectIcon(target.id);
    }
  };

  const handleSubmit = async () => {
    if (!title.trim()) { setError('Title is required'); return; }
    if (!project && !domains.trim()) { setError('At least one scope entry is required'); return; }
    if (!scheduleValid) { setError(project ? 'Select at least one phase' : 'Check the rescan interval and phases'); return; }
    setSaving(true);
    setError('');
    try {
      if (project) await handleUpdate(project);
      else await handleCreate();
      onSaved();
      onClose();
    } catch (e) {
      // The overlay keeps whatever was typed so the operator can correct the
      // field the server named and submit again.
      setError(project ? 'Failed to save' : (e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!project) return;
    setDeleting(true);
    try {
      await deleteProject(project.id);
      onDeleted?.();
    } catch {
      setError('Failed to delete');
      setDeleting(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)',
      WebkitBackdropFilter: 'blur(6px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}>
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)', borderRadius: 'var(--radius-xl)',
        maxWidth: 540, width: '90%',
        boxShadow: 'var(--shadow-elevated)',
        animation: 'fadeIn 150ms ease',
        // The backdrop is fixed and does not scroll, so a card taller than the
        // viewport would put its footer buttons out of reach. Capping the height
        // short of both edges keeps the card on screen; as a column it still
        // sizes to its content, and stays centred, whenever that fits.
        display: 'flex', flexDirection: 'column', maxHeight: 'calc(100vh - 48px)',
        overflow: 'hidden',
        position: 'relative',
      }}>
        {/* Violet top accent */}
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, background: 'linear-gradient(90deg, transparent, rgba(124,107,255,0.3), transparent)' }} />
        <div style={{
          padding: '18px 22px', borderBottom: '1px solid var(--border-subtle)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          flexShrink: 0,
        }}>
          <h3 style={{ color: 'var(--text-primary)', fontSize: 15, fontWeight: 600, margin: 0 }}>
            {project ? 'Edit Project' : 'New Project'}
          </h3>
          {project && (!confirmDelete ? (
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
          ))}
        </div>

        {/* The body is the only scrolling region, so the header and the footer
            stay pinned. minHeight 0 is what makes the card's cap bite: a flex
            child refuses to shrink below its content height without it, and the
            body would push the card past the viewport again. Its own right
            padding plus a stable gutter keeps the scrollbar off the fields and
            stops the schedule toggle from shifting them sideways. */}
        <div style={{
          padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 18,
          overflowY: 'auto', minHeight: 0, scrollbarGutter: 'stable',
        }}>
          {error && (
            <div style={{
              background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)',
              borderRadius: 'var(--radius-md)', padding: '8px 12px', fontSize: 12, color: 'var(--status-error)',
              fontFamily: 'var(--font-mono)',
            }}>{error}</div>
          )}

          {/* Icon upload */}
          <div>
            <label style={labelStyle}>Project Icon</label>
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
              {project && iconPreview && (
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
            <label style={labelStyle}>Title</label>
            <input
              className="input"
              style={fieldStyle}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Project name"
            />
          </div>
          <div>
            <label style={labelStyle}>Description</label>
            <input
              className="input"
              style={fieldStyle}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional"
            />
          </div>
          <div>
            <label style={labelStyle}>Scope (one per line)</label>
            <textarea
              className="input"
              value={domains}
              onChange={(e) => setDomains(e.target.value)}
              rows={5}
              style={{
                ...fieldStyle, fontFamily: 'var(--font-mono)', fontSize: 12,
                resize: 'vertical', lineHeight: 1.6,
              }}
              placeholder={"*.example.com\n*.target.io\nsub.target.io"}
            />
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.5 }}>
              Wildcard domains (*.example.com) define recon scope. Specific hostnames (sub.example.com) are added as assets directly.
            </div>
          </div>

          <ScheduleFields
            enabled={scheduleEnabled}
            intervalValue={intervalValue}
            intervalUnit={intervalUnit}
            phases={phases}
            onChange={(s) => {
              setScheduleEnabled(s.enabled);
              setIntervalValue(s.intervalValue);
              setIntervalUnit(s.intervalUnit);
              setPhases(s.phases);
            }}
          />
        </div>

        <div style={{
          padding: '14px 22px', borderTop: '1px solid var(--border-subtle)',
          display: 'flex', justifyContent: 'flex-end', gap: 8,
          flexShrink: 0,
        }}>
          <button onClick={handleClose} className="btn-secondary">Cancel</button>
          <button onClick={handleSubmit} disabled={saving || !scheduleValid} className="btn-primary">
            {project
              ? (saving ? 'Saving...' : 'Save Changes')
              : (saving ? 'Creating...' : 'Create Project')}
          </button>
        </div>
      </div>
    </div>
  );
}
