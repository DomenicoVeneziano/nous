// frontend/src/components/project/FindingsPanel.tsx
import React, { useEffect, useCallback, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Pencil, Trash2, Plus, Save, RotateCcw, X, ChevronLeft, ChevronRight } from 'lucide-react';
import type { Finding, FindingCreate, Severity } from '../../types/finding';
import { fetchFindings, createFinding, updateFinding, deleteFinding } from '../../api/findings';
import { useAuth } from '../../hooks/useAuth';
import { mdComponents } from '../shared/markdownComponents';

interface Props {
  projectId: string;
  assetId: string;
}

const SEVERITY_STYLE: Record<Severity, { color: string; bg: string; border: string }> = {
  informative: { color: 'var(--status-info)',    bg: 'var(--status-info-bg)',    border: 'var(--status-info-border)'    },
  low:         { color: 'var(--status-success)', bg: 'var(--status-success-bg)', border: 'var(--status-success-border)' },
  medium:      { color: 'var(--status-warning)', bg: 'var(--status-warning-bg)', border: 'var(--status-warning-border)' },
  high:        { color: '#f97316',               bg: 'rgba(249,115,22,0.10)',    border: 'rgba(249,115,22,0.25)'        },
  critical:    { color: 'var(--status-error)',   bg: 'var(--status-error-bg)',   border: 'var(--status-error-border)'   },
};

const SEVERITY_ORDER: Severity[] = ['informative', 'low', 'medium', 'high', 'critical'];

function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.informative;
  return (
    <span style={{
      fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
      letterSpacing: '0.07em', padding: '3px 8px', borderRadius: 'var(--radius-sm)',
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
      textTransform: 'uppercase', flexShrink: 0,
    }}>
      {severity}
    </span>
  );
}

const inputStyle: React.CSSProperties = {
  width: '100%', background: 'var(--bg-elevated)',
  border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
  padding: '6px 10px', fontSize: 12, outline: 'none',
  fontFamily: 'var(--font-mono)',
  transition: 'border-color var(--transition-fast)',
  boxSizing: 'border-box',
};

const labelStyle: React.CSSProperties = {
  color: 'var(--text-muted)', fontSize: 11, marginBottom: 4,
};


export default function FindingsPanel({ projectId, assetId }: Props) {
  const { isAdmin } = useAuth();

  const [findings, setFindings]       = useState<Finding[]>([]);
  const [showCreate, setShowCreate]   = useState(false);
  const [editingId, setEditingId]     = useState<string | null>(null);
  const [deleteId, setDeleteId]       = useState<string | null>(null);
  const [saving, setSaving]           = useState(false);
  const [error, setError]             = useState('');
  const [overlayId, setOverlayId]     = useState<string | null>(null);

  // shared form state (used for both create and edit)
  const [formTitle, setFormTitle]         = useState('');
  const [formSeverity, setFormSeverity]   = useState<Severity>('informative');
  const [formBody, setFormBody]           = useState('');

  const load = () =>
    fetchFindings(projectId, assetId)
      .then(setFindings)
      .catch(() => {});

  useEffect(() => {
    setFindings([]);
    setShowCreate(false);
    setEditingId(null);
    setDeleteId(null);
    setOverlayId(null);
    setError('');
    load();
  }, [assetId]);

  const overlayIndex = overlayId ? findings.findIndex((f) => f.id === overlayId) : -1;

  const closeOverlay = useCallback(() => setOverlayId(null), []);
  const prevFinding  = useCallback(() => {
    if (overlayIndex > 0) setOverlayId(findings[overlayIndex - 1].id);
  }, [overlayIndex, findings]);
  const nextFinding  = useCallback(() => {
    if (overlayIndex < findings.length - 1) setOverlayId(findings[overlayIndex + 1].id);
  }, [overlayIndex, findings]);

  useEffect(() => {
    if (!overlayId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape')      closeOverlay();
      if (e.key === 'ArrowLeft')   prevFinding();
      if (e.key === 'ArrowRight')  nextFinding();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [overlayId, prevFinding, nextFinding, closeOverlay]);

  const resetForm = () => {
    setFormTitle(''); setFormSeverity('informative'); setFormBody('');
    setError('');
  };

  const handleCreate = async () => {
    if (!formTitle.trim()) return;
    setSaving(true); setError('');
    try {
      const payload: FindingCreate = { title: formTitle.trim(), severity: formSeverity, body: formBody };
      await createFinding(projectId, assetId, payload);
      resetForm(); setShowCreate(false);
      load();
    } catch {
      setError('Failed to create finding');
    } finally {
      setSaving(false);
    }
  };

  const startEdit = (f: Finding) => {
    setEditingId(f.id);
    setFormTitle(f.title);
    setFormSeverity(f.severity as Severity);
    setFormBody(f.body);
    setShowCreate(false);
    setError('');
  };

  const handleUpdate = async (findingId: string) => {
    if (!formTitle.trim()) return;
    setSaving(true); setError('');
    try {
      await updateFinding(projectId, assetId, findingId, {
        title: formTitle.trim(), severity: formSeverity, body: formBody,
      });
      setEditingId(null); resetForm();
      load();
    } catch {
      setError('Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const cancelEdit = () => { setEditingId(null); resetForm(); };

  const handleDelete = async (findingId: string) => {
    try {
      await deleteFinding(projectId, assetId, findingId);
      setDeleteId(null);
      load();
    } catch {
      setError('Failed to delete');
    }
  };

  return (
    <div>
      {/* Section header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{
          fontSize: 10, fontWeight: 600, color: 'var(--text-muted)',
          textTransform: 'uppercase', letterSpacing: '0.08em',
        }}>
          Findings {findings.length > 0 && `(${findings.length})`}
        </div>
        {isAdmin && !showCreate && (
          <button
            onClick={() => { setShowCreate(true); setEditingId(null); resetForm(); }}
            style={{
              background: 'transparent', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
              padding: '3px 8px', fontSize: 11, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 4,
              transition: 'all var(--transition-fast)',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--accent-primary)'; e.currentTarget.style.borderColor = 'var(--accent-border)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
          >
            <Plus size={11} /> Add Finding
          </button>
        )}
      </div>

      {error && (
        <div style={{
          background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)',
          borderRadius: 'var(--radius-md)', padding: '5px 10px', fontSize: 11,
          color: 'var(--status-error)', fontFamily: 'var(--font-mono)', marginBottom: 10,
        }}>{error}</div>
      )}

      {/* Create form */}
      {showCreate && (
        <FindingForm
          title={formTitle} setTitle={setFormTitle}
          severity={formSeverity} setSeverity={setFormSeverity}
          body={formBody} setBody={setFormBody}
          saving={saving}
          onSave={handleCreate}
          onCancel={() => { setShowCreate(false); resetForm(); }}
        />
      )}

      {/* Finding list */}
      {findings.length === 0 && !showCreate ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
          No findings yet.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {findings.map((f) => (
            <div
              key={f.id}
              style={{
                background: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)', padding: '10px 12px',
              }}
            >
              {editingId === f.id ? (
                /* ── Edit form ── */
                <FindingForm
                  title={formTitle} setTitle={setFormTitle}
                  severity={formSeverity} setSeverity={setFormSeverity}
                  body={formBody} setBody={setFormBody}
                  saving={saving}
                  onSave={() => handleUpdate(f.id)}
                  onCancel={cancelEdit}
                />
              ) : (
                /* ── Saved view ── */
                <div
                  onClick={() => setOverlayId(f.id)}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
                >
                  <SeverityBadge severity={f.severity as Severity} />
                  <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {f.title}
                  </span>
                  {isAdmin && (
                    <div
                      style={{ display: 'flex', gap: 4, flexShrink: 0 }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {deleteId === f.id ? (
                        <>
                          <button
                            onClick={() => handleDelete(f.id)}
                            style={{
                              background: 'var(--status-error-bg)', color: 'var(--status-error)',
                              border: '1px solid var(--status-error-border)', borderRadius: 'var(--radius-sm)',
                              padding: '3px 8px', fontSize: 11, fontWeight: 600, cursor: 'pointer',
                              fontFamily: 'var(--font-mono)',
                            }}
                          >Confirm</button>
                          <button
                            onClick={() => setDeleteId(null)}
                            style={{
                              background: 'transparent', color: 'var(--text-muted)',
                              border: '1px solid var(--border-default)', borderRadius: 'var(--radius-sm)',
                              padding: '3px 8px', fontSize: 11, cursor: 'pointer',
                            }}
                          >Cancel</button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => startEdit(f)}
                            title="Edit"
                            style={{
                              background: 'transparent', border: '1px solid var(--border-default)',
                              borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
                              padding: '3px 6px', cursor: 'pointer', display: 'flex', alignItems: 'center',
                              transition: 'all var(--transition-fast)',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.filter = 'brightness(1.3)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.filter = 'brightness(1)'; }}
                          ><Pencil size={11} /></button>
                          <button
                            onClick={() => setDeleteId(f.id)}
                            title="Delete"
                            style={{
                              background: 'transparent', border: '1px solid var(--border-default)',
                              borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
                              padding: '3px 6px', cursor: 'pointer', display: 'flex', alignItems: 'center',
                              transition: 'all var(--transition-fast)',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; e.currentTarget.style.borderColor = 'var(--status-error-border)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
                          ><Trash2 size={11} /></button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Finding overlay ── */}
      {overlayId && overlayIndex !== -1 && (() => {
        const f = findings[overlayIndex];
        return (
          <div
            onClick={closeOverlay}
            style={{
              position: 'fixed', inset: 0, zIndex: 1000,
              background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(2px)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: 24,
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-lg)', width: '100%', maxWidth: 680,
                maxHeight: '80vh', display: 'flex', flexDirection: 'column',
                boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
              }}
            >
              {/* Overlay header */}
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '14px 16px', borderBottom: '1px solid var(--border-subtle)',
                flexShrink: 0,
              }}>
                <SeverityBadge severity={f.severity as Severity} />
                <span style={{ flex: 1, fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
                  {f.title}
                </span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginRight: 8 }}>
                  {overlayIndex + 1} / {findings.length}
                </span>
                <button
                  onClick={closeOverlay}
                  title="Close (Esc)"
                  style={{
                    background: 'transparent', border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
                    padding: '3px 6px', cursor: 'pointer', display: 'flex', alignItems: 'center',
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
                ><X size={13} /></button>
              </div>

              {/* Overlay body */}
              <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px' }}>
                {f.body ? (
                  <ReactMarkdown components={mdComponents}>{f.body}</ReactMarkdown>
                ) : (
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                    No description.
                  </span>
                )}
              </div>

              {/* Overlay footer — prev / next */}
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '10px 16px', borderTop: '1px solid var(--border-subtle)', flexShrink: 0,
              }}>
                <button
                  onClick={prevFinding}
                  disabled={overlayIndex === 0}
                  title="Previous finding (←)"
                  style={{
                    background: 'transparent', border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)', color: overlayIndex === 0 ? 'var(--text-disabled)' : 'var(--text-muted)',
                    padding: '5px 12px', fontSize: 11, cursor: overlayIndex === 0 ? 'not-allowed' : 'pointer',
                    display: 'flex', alignItems: 'center', gap: 4,
                    opacity: overlayIndex === 0 ? 0.4 : 1,
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { if (overlayIndex > 0) e.currentTarget.style.color = 'var(--text-primary)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = overlayIndex === 0 ? 'var(--text-disabled)' : 'var(--text-muted)'; }}
                >
                  <ChevronLeft size={13} /> Previous
                </button>
                <button
                  onClick={nextFinding}
                  disabled={overlayIndex === findings.length - 1}
                  title="Next finding (→)"
                  style={{
                    background: 'transparent', border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)', color: overlayIndex === findings.length - 1 ? 'var(--text-disabled)' : 'var(--text-muted)',
                    padding: '5px 12px', fontSize: 11, cursor: overlayIndex === findings.length - 1 ? 'not-allowed' : 'pointer',
                    display: 'flex', alignItems: 'center', gap: 4,
                    opacity: overlayIndex === findings.length - 1 ? 0.4 : 1,
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { if (overlayIndex < findings.length - 1) e.currentTarget.style.color = 'var(--text-primary)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = overlayIndex === findings.length - 1 ? 'var(--text-disabled)' : 'var(--text-muted)'; }}
                >
                  Next <ChevronRight size={13} />
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

/* ── Shared form used for both create and edit ── */
interface FormProps {
  title: string;       setTitle: (v: string) => void;
  severity: Severity;  setSeverity: (v: Severity) => void;
  body: string;        setBody: (v: string) => void;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}

function FindingForm({ title, setTitle, severity, setSeverity, body, setBody, saving, onSave, onCancel }: FormProps) {
  return (
    <div style={{
      background: 'var(--bg-base)', border: '1px solid var(--border-default)',
      borderRadius: 'var(--radius-md)', padding: '12px 12px 10px', marginBottom: 8,
      display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      {/* Title + Severity row */}
      <div style={{ display: 'flex', gap: 8 }}>
        <div style={{ flex: 1 }}>
          <div style={labelStyle}>Title</div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Finding title"
            style={inputStyle}
            onKeyDown={(e) => { if (e.key === 'Enter') onSave(); if (e.key === 'Escape') onCancel(); }}
            autoFocus
          />
        </div>
        <div style={{ width: 110 }}>
          <div style={labelStyle}>Severity</div>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as Severity)}
            style={{ ...inputStyle, cursor: 'pointer' }}
          >
            {SEVERITY_ORDER.map((s) => (
              <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Body */}
      <div>
        <div style={labelStyle}>Body (Markdown)</div>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={8}
          placeholder={"## Summary\n\nDescribe the finding...\n\n## Steps to Reproduce\n\n1. ..."}
          style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.6, fontSize: 11 }}
        />
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          onClick={onSave}
          disabled={saving || !title.trim()}
          className="btn-primary"
          style={{
            padding: '5px 12px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4,
            opacity: saving || !title.trim() ? 0.6 : 1,
            cursor: saving || !title.trim() ? 'not-allowed' : 'pointer',
          }}
        >
          <Save size={11} /> {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={onCancel}
          className="btn-secondary"
          style={{ padding: '5px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}
        >
          <RotateCcw size={11} /> Cancel
        </button>
      </div>
    </div>
  );
}
