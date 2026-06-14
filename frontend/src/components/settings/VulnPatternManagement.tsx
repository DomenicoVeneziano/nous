// frontend/src/components/settings/VulnPatternManagement.tsx
import React, { useEffect, useState } from 'react';
import { Plus, Pencil, Trash2, X, Save, PlayCircle, ChevronDown } from 'lucide-react';
import type { VulnPattern, VulnPatternCheck } from '../../types/vulnPattern';
import {
  fetchVulnPatterns, createVulnPattern, updateVulnPattern,
  deleteVulnPattern, testVulnPattern,
} from '../../api/vulnPatterns';
import ConfirmModal from '../shared/ConfirmModal';
import { useProjectStore } from '../../store/projectStore';

const VALID_FIELDS = ['hostname', 'tech', 'status', 'title', 'content', 'content_length',
  'dns', 'url', 'type', 'date', 'header', 'body'];

const inputStyle: React.CSSProperties = {
  background: 'var(--bg-base)', border: '1px solid var(--border-default)',
  borderRadius: 6, color: 'var(--text-primary)', padding: '7px 10px',
  fontSize: 12, outline: 'none', fontFamily: 'var(--font-mono)',
  transition: 'border-color var(--transition-fast)',
  boxSizing: 'border-box',
};

const labelStyle: React.CSSProperties = {
  fontSize: 11, color: 'var(--text-muted)', marginBottom: 4,
};

const thStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  padding: '8px 14px', textAlign: 'left',
  borderBottom: '1px solid var(--border-subtle)',
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '10px 14px', fontSize: 12,
  borderBottom: '1px solid var(--border-subtle)',
  verticalAlign: 'middle',
};

function ChecksEditor({
  checks, onChange,
}: { checks: VulnPatternCheck[]; onChange: (checks: VulnPatternCheck[]) => void }) {
  const addCheck = () => onChange([...checks, { field: 'body', regex: '' }]);
  const removeCheck = (i: number) => onChange(checks.filter((_, idx) => idx !== i));
  const updateCheck = (i: number, key: keyof VulnPatternCheck, val: string) => {
    const next = checks.map((c, idx) => idx === i ? { ...c, [key]: val } : c);
    onChange(next);
  };

  return (
    <div>
      <div style={{ ...labelStyle, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Checks (OR logic — any match triggers the pattern)</span>
        <button
          onClick={addCheck}
          style={{
            background: 'transparent', border: '1px solid var(--border-default)',
            borderRadius: 4, color: 'var(--text-muted)', padding: '2px 7px',
            fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 3,
          }}
        >
          <Plus size={10} /> Add check
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
        {checks.map((check, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <select
              value={check.field}
              onChange={(e) => updateCheck(i, 'field', e.target.value)}
              style={{ ...inputStyle, width: 120, cursor: 'pointer', flexShrink: 0 }}
            >
              {VALID_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <input
              value={check.regex}
              onChange={(e) => updateCheck(i, 'regex', e.target.value)}
              placeholder="regex pattern"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={() => removeCheck(i)}
              disabled={checks.length <= 1}
              style={{
                background: 'transparent', border: '1px solid var(--border-default)',
                borderRadius: 4, color: 'var(--text-muted)', padding: '5px 7px',
                cursor: checks.length <= 1 ? 'not-allowed' : 'pointer',
                opacity: checks.length <= 1 ? 0.4 : 1, display: 'flex', alignItems: 'center',
                flexShrink: 0,
              }}
            >
              <X size={11} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

interface EditState {
  description: string;
  checks: VulnPatternCheck[];
  saving: boolean;
  error: string;
}

export default function VulnPatternManagement() {
  const [patterns, setPatterns] = useState<VulnPattern[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newChecks, setNewChecks] = useState<VulnPatternCheck[]>([{ field: 'body', regex: '' }]);
  const [createError, setCreateError] = useState('');
  const [creating, setCreating] = useState(false);
  const [editStates, setEditStates] = useState<Record<string, EditState>>({});
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { count: number; loading: boolean }>>({});
  const { projects, loadProjects } = useProjectStore();
  const [testProjectId, setTestProjectId] = useState('');

  const load = () => fetchVulnPatterns().then(setPatterns).catch(() => {});

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (projects.length === 0) loadProjects();
  }, []);
  useEffect(() => {
    if (projects.length > 0 && !testProjectId) setTestProjectId(projects[0].id);
  }, [projects]);

  const handleCreate = async () => {
    if (!newName.trim() || !newDesc.trim()) return;
    if (newChecks.some((c) => !c.regex.trim())) { setCreateError('All checks must have a regex pattern'); return; }
    setCreating(true); setCreateError('');
    try {
      await createVulnPattern({ name: newName.trim(), description: newDesc.trim(), checks: newChecks });
      setNewName(''); setNewDesc(''); setNewChecks([{ field: 'body', regex: '' }]);
      setShowCreate(false);
      load();
    } catch (e: any) {
      setCreateError(e?.response?.data?.detail ?? 'Failed to create pattern');
    } finally {
      setCreating(false);
    }
  };

  const startEdit = (p: VulnPattern) => {
    setEditStates((prev) => ({
      ...prev,
      [p.id]: { description: p.description, checks: JSON.parse(JSON.stringify(p.checks)), saving: false, error: '' },
    }));
  };

  const cancelEdit = (id: string) => {
    setEditStates((prev) => { const next = { ...prev }; delete next[id]; return next; });
  };

  const saveEdit = async (p: VulnPattern) => {
    const state = editStates[p.id];
    if (!state) return;
    if (state.checks.some((c) => !c.regex.trim())) {
      setEditStates((prev) => ({ ...prev, [p.id]: { ...prev[p.id], error: 'All checks must have a regex pattern' } }));
      return;
    }
    setEditStates((prev) => ({ ...prev, [p.id]: { ...prev[p.id], saving: true, error: '' } }));
    try {
      await updateVulnPattern(p.id, { description: state.description, checks: state.checks });
      cancelEdit(p.id);
      load();
    } catch (e: any) {
      setEditStates((prev) => ({ ...prev, [p.id]: { ...prev[p.id], saving: false, error: e?.response?.data?.detail ?? 'Failed to save' } }));
    }
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    await deleteVulnPattern(deleteId).catch(() => {});
    setDeleteId(null);
    load();
  };

  const handleTest = async (p: VulnPattern) => {
    if (!testProjectId) return;
    setTestResults((prev) => ({ ...prev, [p.id]: { count: 0, loading: true } }));
    try {
      const result = await testVulnPattern(p.id, testProjectId);
      setTestResults((prev) => ({ ...prev, [p.id]: { count: result.match_count, loading: false } }));
    } catch {
      setTestResults((prev) => ({ ...prev, [p.id]: { count: -1, loading: false } }));
    }
  };

  return (
    <div>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {/* Header */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '14px 16px', borderBottom: showCreate ? '1px solid var(--border-subtle)' : undefined,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
            Vulnerability Patterns
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {projects.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Test against:</span>
                <select
                  value={testProjectId}
                  onChange={(e) => setTestProjectId(e.target.value)}
                  style={{ ...inputStyle, padding: '4px 8px', fontSize: 11, cursor: 'pointer' }}
                >
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
                </select>
              </div>
            )}
            <button
              onClick={() => { setShowCreate(!showCreate); setCreateError(''); }}
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                background: 'var(--accent-primary)', color: 'var(--bg-base)',
                border: '1px solid var(--accent-dim)',
                borderRadius: 6, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
              }}
            >
              <Plus size={12} /> Add Pattern
            </button>
          </div>
        </div>

        {/* Create form */}
        {showCreate && (
          <div style={{
            padding: '14px 16px', borderBottom: '1px solid var(--border-subtle)',
            background: 'var(--bg-base)',
          }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 10, marginBottom: 10 }}>
              <div>
                <div style={labelStyle}>Name (lowercase, underscores only)</div>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. jwt_tokens"
                  style={{ ...inputStyle, width: '100%' }}
                />
              </div>
              <div>
                <div style={labelStyle}>Description</div>
                <input
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="What this pattern detects"
                  style={{ ...inputStyle, width: '100%' }}
                />
              </div>
            </div>
            <div style={{ marginBottom: 12 }}>
              <ChecksEditor checks={newChecks} onChange={setNewChecks} />
            </div>
            {createError && (
              <div style={{
                background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)',
                borderRadius: 6, padding: '5px 10px', fontSize: 11, color: 'var(--status-error)',
                fontFamily: 'var(--font-mono)', marginBottom: 10,
              }}>{createError}</div>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={handleCreate}
                disabled={creating || !newName.trim() || !newDesc.trim()}
                className="btn-primary"
                style={{
                  padding: '6px 14px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4,
                  opacity: creating || !newName.trim() || !newDesc.trim() ? 0.6 : 1,
                  cursor: creating || !newName.trim() || !newDesc.trim() ? 'not-allowed' : 'pointer',
                }}
              >
                <Save size={12} /> {creating ? 'Creating...' : 'Create'}
              </button>
              <button
                onClick={() => { setShowCreate(false); setCreateError(''); }}
                className="btn-secondary"
                style={{ padding: '6px 12px', fontSize: 12 }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Table */}
        {patterns.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
            No patterns yet. Add one above to start detecting vulnerabilities in search.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-surface)' }}>
                <th style={thStyle}>Name</th>
                <th style={thStyle}>Description</th>
                <th style={{ ...thStyle, width: 70, textAlign: 'center' }}>Checks</th>
                <th style={{ ...thStyle, width: 100, textAlign: 'center' }}>Test Result</th>
                <th style={{ ...thStyle, width: 120 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {patterns.map((p) => {
                const editing = editStates[p.id];
                const testResult = testResults[p.id];
                return (
                  <React.Fragment key={p.id}>
                    <tr style={{ background: editing ? 'var(--bg-base)' : 'transparent' }}>
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                          <code style={{
                            fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--accent-primary)',
                            background: 'var(--accent-subtle)', padding: '2px 6px', borderRadius: 4,
                          }}>
                            vuln:{p.name}
                          </code>
                          {p.is_default && (
                            <span style={{
                              fontSize: 9, fontWeight: 700, letterSpacing: '0.07em',
                              color: 'var(--text-muted)', background: 'var(--bg-surface)',
                              border: '1px solid var(--border-subtle)',
                              padding: '2px 6px', borderRadius: 4, textTransform: 'uppercase',
                            }}>Default</span>
                          )}
                        </div>
                      </td>
                      <td style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                        {editing ? (
                          <input
                            value={editing.description}
                            onChange={(e) => setEditStates((prev) => ({
                              ...prev, [p.id]: { ...prev[p.id], description: e.target.value },
                            }))}
                            style={{ ...inputStyle, width: '100%' }}
                          />
                        ) : p.description}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'center', color: 'var(--text-muted)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                          <span>{p.checks.length}</span>
                          {!editing && (
                            <button
                              onClick={() => startEdit(p)}
                              title="View checks"
                              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex', padding: 0 }}
                            >
                              <ChevronDown size={12} />
                            </button>
                          )}
                        </div>
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'center' }}>
                        {testResult ? (
                          testResult.loading ? (
                            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Testing...</span>
                          ) : testResult.count < 0 ? (
                            <span style={{ fontSize: 11, color: 'var(--status-error)' }}>Error</span>
                          ) : (
                            <span style={{
                              fontSize: 12, fontWeight: 600,
                              color: testResult.count > 0 ? 'var(--status-warning)' : 'var(--text-muted)',
                            }}>
                              {testResult.count} match{testResult.count !== 1 ? 'es' : ''}
                            </span>
                          )
                        ) : (
                          <button
                            onClick={() => handleTest(p)}
                            disabled={!testProjectId}
                            title="Test pattern against selected project"
                            style={{
                              display: 'flex', alignItems: 'center', gap: 4, margin: '0 auto',
                              background: 'transparent', border: '1px solid var(--border-default)',
                              borderRadius: 4, color: 'var(--text-muted)', padding: '3px 8px',
                              fontSize: 11, cursor: testProjectId ? 'pointer' : 'not-allowed',
                              opacity: testProjectId ? 1 : 0.4,
                              transition: 'all var(--transition-fast)',
                            }}
                            onMouseEnter={(e) => { if (testProjectId) e.currentTarget.style.color = 'var(--accent-primary)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
                          >
                            <PlayCircle size={11} /> Test
                          </button>
                        )}
                      </td>
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', gap: 5 }}>
                          {editing ? (
                            <>
                              <button
                                onClick={() => saveEdit(p)}
                                disabled={editing.saving}
                                className="btn-primary"
                                style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 3 }}
                              >
                                <Save size={10} /> Save
                              </button>
                              <button
                                onClick={() => cancelEdit(p.id)}
                                className="btn-secondary"
                                style={{ padding: '4px 8px', fontSize: 11 }}
                              >
                                Cancel
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                onClick={() => startEdit(p)}
                                title="Edit"
                                style={{
                                  background: 'transparent', border: '1px solid var(--border-default)',
                                  borderRadius: 4, color: 'var(--text-muted)', padding: '4px 7px',
                                  cursor: 'pointer', display: 'flex', alignItems: 'center',
                                  transition: 'all var(--transition-fast)',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-secondary)'; }}
                                onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
                              >
                                <Pencil size={11} />
                              </button>
                              {!p.is_default && (
                                <button
                                  onClick={() => setDeleteId(p.id)}
                                  title="Delete"
                                  style={{
                                    background: 'transparent', border: '1px solid var(--border-default)',
                                    borderRadius: 4, color: 'var(--text-muted)', padding: '4px 7px',
                                    cursor: 'pointer', display: 'flex', alignItems: 'center',
                                    transition: 'all var(--transition-fast)',
                                  }}
                                  onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; e.currentTarget.style.borderColor = 'var(--status-error-border)'; }}
                                  onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
                                >
                                  <Trash2 size={11} />
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* Expanded checks editor */}
                    {editing && (
                      <tr style={{ background: 'var(--bg-base)' }}>
                        <td colSpan={5} style={{ padding: '0 14px 14px' }}>
                          <ChecksEditor
                            checks={editing.checks}
                            onChange={(checks) => setEditStates((prev) => ({ ...prev, [p.id]: { ...prev[p.id], checks } }))}
                          />
                          {editing.error && (
                            <div style={{
                              marginTop: 8, background: 'var(--status-error-bg)',
                              border: '1px solid var(--status-error-border)',
                              borderRadius: 6, padding: '5px 10px', fontSize: 11,
                              color: 'var(--status-error)', fontFamily: 'var(--font-mono)',
                            }}>{editing.error}</div>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <ConfirmModal
        open={!!deleteId}
        title="Delete Pattern"
        message="Are you sure you want to delete this vulnerability pattern? This cannot be undone."
        onConfirm={handleDelete}
        onCancel={() => setDeleteId(null)}
        destructive
      />
    </div>
  );
}
