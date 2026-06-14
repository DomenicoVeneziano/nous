// frontend/src/components/data/FileExplorer.tsx
import React, { useState, useEffect } from 'react';
import { File, FolderOpen, Pencil, Eye, Save } from 'lucide-react';
import client from '../../api/client';
import { saveFileContent } from '../../api/settings';
import { useAuth } from '../../hooks/useAuth';

interface Props {
  projectId: string | null;
}


export default function FileExplorer({ projectId }: Props) {
  const [files, setFiles] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [content, setContent] = useState<string>('');
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const { isAdmin } = useAuth();

  useEffect(() => {
    if (!projectId) return;
    client.get('/files/tree', { params: { project_id: projectId } })
      .then((r) => setFiles(r.data.files || []))
      .catch(() => setFiles([]));
  }, [projectId]);

  const handleFileClick = async (path: string) => {
    setSelectedFile(path);
    setEditing(false);
    setSaveMsg('');
    try {
      const r = await client.get('/files/content', {
        params: { path },
        responseType: 'text',
        transformResponse: [(data: unknown) => data],
      });
      const text = typeof r.data === 'string' ? r.data : JSON.stringify(r.data, null, 2);
      setContent(text);
      setEditContent(text);
    } catch {
      setContent('Failed to load file');
      setEditContent('');
    }
  };

  const handleStartEdit = () => {
    setEditContent(content);
    setEditing(true);
    setSaveMsg('');
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setEditContent(content);
    setSaveMsg('');
  };

  const handleSave = async () => {
    if (!selectedFile) return;
    setSaving(true);
    setSaveMsg('');
    try {
      await saveFileContent(selectedFile, editContent);
      setContent(editContent);
      setEditing(false);
      setSaveMsg('Saved');
      setTimeout(() => setSaveMsg(''), 2500);
    } catch {
      setSaveMsg('Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!projectId) {
    return (
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
        borderRadius: 8, padding: 28, textAlign: 'center', color: 'var(--text-muted)',
        fontSize: 14, fontFamily: 'var(--font-mono)',
      }}>
        Select a project to browse files
      </div>
    );
  }

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, overflow: 'hidden', display: 'flex', height: 460,
      boxShadow: 'var(--shadow-card)',
    }}>
      {/* File tree */}
      <div style={{
        width: 260, borderRight: '1px solid var(--border-subtle)', overflow: 'auto',
        padding: 0,
      }}>
        <div style={{
          padding: '13px 16px', fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
          borderBottom: '1px solid var(--border-subtle)',
          textTransform: 'uppercase', letterSpacing: '0.08em',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <FolderOpen size={13} color="var(--text-muted)" />
          Files
        </div>
        {files.length === 0 && (
          <div style={{
            padding: '20px 16px', color: 'var(--text-muted)', fontSize: 13,
            fontFamily: 'var(--font-mono)',
          }}>
            No files yet. Run a recon scan to generate results.
          </div>
        )}
        {files.map((f) => (
          <button
            key={f}
            onClick={() => handleFileClick(f)}
            style={{
              display: 'flex', alignItems: 'center', gap: 7, width: '100%',
              backgroundColor: selectedFile === f ? 'var(--bg-selected)' : 'transparent',
              border: 'none', borderRadius: 0, cursor: 'pointer',
              borderLeft: selectedFile === f ? '2px solid var(--accent-primary)' : '2px solid transparent',
              padding: '8px 14px', color: selectedFile === f ? 'var(--text-primary)' : 'var(--text-secondary)',
              fontSize: 13, fontFamily: 'var(--font-mono)', textAlign: 'left',
              transition: 'all var(--transition-fast)',
            }}
            onMouseEnter={(e) => {
              if (selectedFile !== f) e.currentTarget.style.backgroundColor = 'var(--bg-hover)';
            }}
            onMouseLeave={(e) => {
              if (selectedFile !== f) e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <File size={12} color={selectedFile === f ? 'var(--accent-primary)' : 'var(--text-muted)'} />
            {f.split('/').pop()}
          </button>
        ))}
      </div>

      {/* Content viewer / editor */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-void)' }}>
        {/* Toolbar */}
        {selectedFile && (
          <div style={{
            padding: '8px 14px', borderBottom: '1px solid var(--border-subtle)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'var(--bg-surface)',
          }}>
            <span style={{
              fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {selectedFile.split('/').pop()}
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {saveMsg && (
                <span style={{
                  fontSize: 12, fontFamily: 'var(--font-mono)',
                  color: saveMsg === 'Saved' ? 'var(--status-success)' : 'var(--status-error)',
                }}>{saveMsg}</span>
              )}
              {isAdmin && !editing && (
                <button onClick={handleStartEdit} title="Edit file" style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  background: 'var(--bg-elevated)',
                  color: 'var(--text-secondary)', border: '1px solid var(--border-default)',
                  borderRadius: 5, padding: '4px 10px', fontSize: 12, fontWeight: 500, cursor: 'pointer',
                  transition: 'all var(--transition-fast)',
                }}>
                  <Pencil size={12} /> Edit
                </button>
              )}
              {editing && (
                <>
                  <button onClick={handleSave} disabled={saving} title="Save" style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    background: 'var(--accent-primary)',
                    color: '#fff', border: '1px solid var(--accent-dim)',
                    borderRadius: 5, padding: '4px 10px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                    opacity: saving ? 0.6 : 1,
                    transition: 'all var(--transition-fast)',
                  }}>
                    <Save size={12} /> Save
                  </button>
                  <button onClick={handleCancelEdit} title="Cancel" style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    background: 'transparent', color: 'var(--text-muted)',
                    border: '1px solid var(--border-default)',
                    borderRadius: 5, padding: '4px 10px', fontSize: 12, fontWeight: 500, cursor: 'pointer',
                    transition: 'all var(--transition-fast)',
                  }}>
                    <Eye size={12} /> View
                  </button>
                </>
              )}
            </div>
          </div>
        )}

        {/* Content area */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          {editing ? (
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              style={{
                width: '100%', height: '100%', resize: 'none',
                background: 'transparent', border: 'none', outline: 'none',
                padding: 16, margin: 0,
                fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-code)',
                lineHeight: 1.6,
              }}
              spellCheck={false}
            />
          ) : (
            <pre style={{
              padding: 16, margin: 0, height: '100%',
              fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-code)',
              whiteSpace: 'pre-wrap', wordBreak: 'break-all', lineHeight: 1.6,
            }}>
              {selectedFile ? content : (
                <span style={{ color: 'var(--text-muted)' }}>Select a file to view its contents</span>
              )}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
