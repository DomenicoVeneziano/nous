// frontend/src/components/projects/NewProjectOverlay.tsx
import React, { useState, useRef } from 'react';
import { createProject, uploadProjectIcon } from '../../api/projects';
import type { ProjectCreate, ScanPhase, ScheduleUnit } from '../../types/project';
import { Upload, X } from 'lucide-react';
import ScheduleFields, { isScheduleValid } from './ScheduleFields';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

/** Pull FastAPI's `detail` off a failed request so the operator sees the
 *  server's reason (a rejected domain, an interval out of range) instead of the
 *  overlay sitting there as if nothing happened. `detail` is a string for an
 *  explicit HTTPException and a list of error objects for a pydantic-level 422,
 *  so both shapes are rendered; a transport-level failure falls back to the
 *  error's own message. */
function errorDetail(reason: unknown): string {
  const detail = (reason as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.flatMap((entry) => {
      const { msg, loc } = (entry ?? {}) as { msg?: unknown; loc?: unknown };
      if (typeof msg !== 'string') return [];
      // `loc` reads like ['body', 'title']; only its tail names the field the
      // operator can act on, so the envelope prefix is dropped.
      const field = Array.isArray(loc) ? loc[loc.length - 1] : undefined;
      return [typeof field === 'string' || typeof field === 'number' ? `${field}: ${msg}` : msg];
    });
    if (parts.length > 0) return parts.join('; ');
  }
  if (reason instanceof Error && reason.message) return reason.message;
  return 'Request failed';
}


export default function NewProjectOverlay({ open, onClose, onCreated }: Props) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [domains, setDomains] = useState('');
  const [iconFile, setIconFile] = useState<File | null>(null);
  const [iconPreview, setIconPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [intervalValue, setIntervalValue] = useState(7);
  const [intervalUnit, setIntervalUnit] = useState<ScheduleUnit>('days');
  const [phases, setPhases] = useState<ScanPhase[]>(['recon']);
  const fileRef = useRef<HTMLInputElement>(null);

  const schedule = { enabled: scheduleEnabled, intervalValue, intervalUnit, phases };
  const scheduleValid = isScheduleValid(schedule);

  if (!open) return null;

  const handleIconSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIconFile(file);
    const reader = new FileReader();
    reader.onload = () => setIconPreview(reader.result as string);
    reader.readAsDataURL(file);
  };

  const clearIcon = () => {
    setIconFile(null);
    setIconPreview(null);
    if (fileRef.current) fileRef.current.value = '';
  };

  // The overlay stays mounted between openings, so a failed attempt would
  // otherwise greet the operator with its old banner the next time around.
  const handleClose = () => {
    setError('');
    onClose();
  };

  const handleSubmit = async () => {
    if (!title.trim()) { setError('Title is required'); return; }
    if (!domains.trim()) { setError('At least one scope entry is required'); return; }
    if (!scheduleValid) { setError('Check the rescan interval and phases'); return; }
    setLoading(true);
    setError('');
    try {
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
      const project = await createProject(payload);
      if (iconFile) {
        try { await uploadProjectIcon(project.id, iconFile); } catch { /* non-fatal */ }
      }
      setTitle('');
      setDescription('');
      setDomains('');
      setScheduleEnabled(false);
      setIntervalValue(7);
      setIntervalUnit('days');
      setPhases(['recon']);
      clearIcon();
      onCreated();
      onClose();
    } catch (e) {
      // The overlay keeps whatever was typed so the operator can correct the
      // field the server named and submit again.
      setError(errorDetail(e));
    } finally {
      setLoading(false);
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
    }} onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}>
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)', borderRadius: 'var(--radius-xl)',
        maxWidth: 540, width: '90%',
        boxShadow: 'var(--shadow-elevated)',
        animation: 'fadeIn 150ms ease',
        overflow: 'hidden',
        position: 'relative',
      }}>
        {/* Violet top accent */}
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, background: 'linear-gradient(90deg, transparent, rgba(124,107,255,0.3), transparent)' }} />
        <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border-subtle)' }}>
          <h3 style={{ color: 'var(--text-primary)', fontSize: 15, fontWeight: 600, margin: 0 }}>New Project</h3>
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
                    alt="Icon preview"
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
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>PNG, JPG, GIF, WebP, SVG — max 2MB</span>
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>Title</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle} placeholder="Project name" />
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
        }}>
          <button onClick={handleClose} className="btn-secondary">Cancel</button>
          <button onClick={handleSubmit} disabled={loading || !scheduleValid} className="btn-primary">
            {loading ? 'Creating...' : 'Create Project'}
          </button>
        </div>
      </div>
    </div>
  );
}
