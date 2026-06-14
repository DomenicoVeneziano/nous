// frontend/src/components/project/AssetDetail.tsx
import React, { useEffect, useState } from 'react';
import { X, Pencil, Trash2, Save, RotateCcw } from 'lucide-react';
import type { Asset, AssetUpdate, Highlight } from '../../types/asset';
import { HighlightText } from '../shared/HighlightText';
import { updateAsset, deleteAsset, fetchImageObjectUrl } from '../../api/assets';
import client from '../../api/client';
import { useAuth } from '../../hooks/useAuth';
import FindingsPanel from './FindingsPanel';

interface Props {
  asset: Asset | null;
  highlights?: Highlight[];
  onClose: () => void;
  onAssetUpdated?: () => void;
  onAssetDeleted?: () => void;
}

function statusColor(code: number | null): string {
  if (!code) return 'var(--text-muted)';
  if (code >= 200 && code < 300) return 'var(--status-success)';
  if (code >= 300 && code < 400) return 'var(--status-info)';
  if (code >= 400 && code < 500) return 'var(--status-warning)';
  return 'var(--status-error)';
}

function getHls(highlights: Highlight[] | undefined, source: string): Highlight[] {
  return (highlights || []).filter((h) => h.source === source);
}

/** For file-backed highlights, resolve windowed snippet offsets to absolute positions in fileContent. */
function resolveFileSpans(highlights: Highlight[], fileContent: string): { start: number; end: number }[] {
  const spans: { start: number; end: number }[] = [];
  const cache = new Map<string, number>();
  for (const hl of highlights) {
    let base = cache.get(hl.snippet);
    if (base === undefined) {
      base = fileContent.indexOf(hl.snippet);
      cache.set(hl.snippet, base);
    }
    if (base === -1) continue;
    spans.push({ start: base + hl.start, end: base + hl.end });
  }
  return spans;
}

export default function AssetDetail({ asset, highlights, onClose, onAssetUpdated, onAssetDeleted }: Props) {
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const { isAdmin } = useAuth();

  const [editHostname, setEditHostname] = useState('');
  const [editType, setEditType] = useState<'subdomain' | 'ip'>('subdomain');
  const [editStatus, setEditStatus] = useState('');
  const [editTitle, setEditTitle] = useState('');
  const [editLength, setEditLength] = useState('');
  const [editTech, setEditTech] = useState('');
  const [editDns, setEditDns] = useState('');
  const [editUrls, setEditUrls] = useState('');

  useEffect(() => {
    if (asset?.response_file_path) {
      client.get('/files/content', {
        params: { path: asset.response_file_path },
        responseType: 'text',
        transformResponse: [(data: unknown) => data],
      })
        .then((r) => setFileContent(typeof r.data === 'string' ? r.data : JSON.stringify(r.data, null, 2)))
        .catch(() => setFileContent(null));
    } else {
      setFileContent(null);
    }
  }, [asset?.response_file_path]);

  useEffect(() => {
    const path = asset?.screenshot_path;
    if (!path) {
      setScreenshotUrl(null);
      return;
    }
    let active = true;
    let objectUrl: string | null = null;
    setScreenshotUrl(null);
    fetchImageObjectUrl(path)
      .then((u) => {
        if (active) { objectUrl = u; setScreenshotUrl(u); }
        else URL.revokeObjectURL(u);
      })
      .catch(() => { if (active) setScreenshotUrl(null); });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [asset?.screenshot_path]);

  useEffect(() => {
    setEditing(false);
    setConfirmDelete(false);
    setError('');
  }, [asset?.id]);

  if (!asset) return null;

  // Pre-compute highlight spans for visible fields
  const hostnameHls = getHls(highlights, 'hostname');
  const titleHls = getHls(highlights, 'title');
  const techHls = getHls(highlights, 'tech');
  const urlHls = getHls(highlights, 'url');
  const fileHls = (highlights || []).filter((h) => ['content', 'header', 'body'].includes(h.source));
  const fileSpans = fileContent ? resolveFileSpans(fileHls, fileContent) : [];

  // Summary of matched fields for non-inline fields
  const matchedFieldSummary = (highlights || []).filter(
    (h) => ['content', 'header', 'body', 'dns', 'url', 'severity', 'vuln', 'date', 'type', 'content_length'].includes(h.field)
  );

  const startEdit = () => {
    setEditHostname(asset.asset);
    setEditType(asset.asset_type);
    setEditStatus(asset.status_code != null ? String(asset.status_code) : '');
    setEditTitle(asset.title || '');
    setEditLength(asset.content_length != null ? String(asset.content_length) : '');
    setEditTech(asset.technologies.join(', '));
    setEditDns(asset.dns_records.length > 0 ? JSON.stringify(asset.dns_records, null, 2) : '');
    setEditUrls(asset.crawled_urls.join('\n'));
    setEditing(true);
    setError('');
  };

  const cancelEdit = () => {
    setEditing(false);
    setError('');
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const payload: AssetUpdate = {};
      if (editHostname.trim() !== asset.asset) payload.asset = editHostname.trim();
      if (editType !== asset.asset_type) payload.asset_type = editType;
      const newStatus = editStatus.trim() === '' ? null : parseInt(editStatus, 10);
      if (newStatus !== asset.status_code) payload.status_code = newStatus;
      const newTitle = editTitle.trim() || null;
      if (newTitle !== asset.title) payload.title = newTitle;
      const newLength = editLength.trim() === '' ? null : parseInt(editLength, 10);
      if (newLength !== asset.content_length) payload.content_length = newLength;
      const newTech = editTech.split(',').map((t) => t.trim()).filter(Boolean);
      if (JSON.stringify(newTech) !== JSON.stringify(asset.technologies)) payload.technologies = newTech;
      if (editDns.trim()) {
        try {
          const parsed = JSON.parse(editDns);
          if (JSON.stringify(parsed) !== JSON.stringify(asset.dns_records)) payload.dns_records = parsed;
        } catch {
          setError('Invalid JSON in DNS records');
          setSaving(false);
          return;
        }
      } else if (asset.dns_records.length > 0) {
        payload.dns_records = [];
      }
      const newUrls = editUrls.split('\n').map((u) => u.trim()).filter(Boolean);
      if (JSON.stringify(newUrls) !== JSON.stringify(asset.crawled_urls)) payload.crawled_urls = newUrls;
      if (Object.keys(payload).length > 0) {
        await updateAsset(asset.project_id, asset.id, payload);
      }
      setEditing(false);
      onAssetUpdated?.();
    } catch {
      setError('Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteAsset(asset.project_id, asset.id);
      onAssetDeleted?.();
      onClose();
    } catch {
      setError('Failed to delete');
      setDeleting(false);
    }
  };

  const sectionStyle: React.CSSProperties = {
    marginBottom: 18, paddingBottom: 18, borderBottom: '1px solid var(--border-subtle)',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
    letterSpacing: '0.08em', marginBottom: 8,
  };

  const codeBlockStyle: React.CSSProperties = {
    background: 'var(--bg-void)', border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-md)', padding: 14, fontSize: 11, fontFamily: 'var(--font-mono)',
    color: 'var(--text-code)', overflow: 'auto', lineHeight: 1.6,
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'var(--bg-elevated)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', padding: '6px 10px', fontSize: 12,
    outline: 'none', fontFamily: 'var(--font-mono)',
    transition: 'border-color var(--transition-fast)',
  };

  const fieldLabel: React.CSSProperties = {
    color: 'var(--text-muted)', fontSize: 11, marginBottom: 3,
  };

  return (
    <div style={{
      width: 480, height: '100%', background: 'var(--bg-surface)',
      borderLeft: '1px solid var(--border-subtle)',
      overflow: 'auto', padding: 22, position: 'relative',
      boxShadow: '-4px 0 32px rgba(0,0,0,0.5)',
    }}>
      {/* Top bar: close + actions */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16,
      }}>
        <div style={{ display: 'flex', gap: 6 }}>
          {isAdmin && !editing && (
            <>
              <button onClick={startEdit} className="btn-secondary" style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                <Pencil size={11} /> Edit
              </button>
              {!confirmDelete ? (
                <button onClick={() => setConfirmDelete(true)} style={{
                  background: 'transparent', border: '1px solid var(--border-default)', borderRadius: 'var(--radius-sm)',
                  padding: '4px 10px', fontSize: 11, cursor: 'pointer', color: 'var(--text-muted)',
                  display: 'flex', alignItems: 'center', gap: 4, transition: 'all var(--transition-fast)',
                }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; e.currentTarget.style.borderColor = 'var(--status-error-border)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-default)'; }}
                >
                  <Trash2 size={11} /> Delete
                </button>
              ) : (
                <>
                  <button onClick={handleDelete} disabled={deleting} className="btn-danger" style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                    {deleting ? 'Deleting...' : 'Confirm Delete'}
                  </button>
                  <button onClick={() => setConfirmDelete(false)} className="btn-secondary" style={{ padding: '4px 10px', fontSize: 11 }}>
                    Cancel
                  </button>
                </>
              )}
            </>
          )}
          {editing && (
            <>
              <button onClick={handleSave} disabled={saving} className="btn-primary" style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                <Save size={11} /> {saving ? 'Saving...' : 'Save'}
              </button>
              <button onClick={cancelEdit} className="btn-secondary" style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                <RotateCcw size={11} /> Cancel
              </button>
            </>
          )}
        </div>
        <button onClick={onClose} style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--text-muted)', padding: 4, borderRadius: 'var(--radius-sm)',
          transition: 'color var(--transition-fast)',
        }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-secondary)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
        >
          <X size={16} />
        </button>
      </div>

      {error && (
        <div style={{
          background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)',
          borderRadius: 'var(--radius-md)', padding: '6px 10px', fontSize: 11, color: 'var(--status-error)',
          fontFamily: 'var(--font-mono)', marginBottom: 14,
        }}>{error}</div>
      )}

      {/* Hostname */}
      {editing ? (
        <div style={{ marginBottom: 18 }}>
          <div style={fieldLabel}>Hostname / IP</div>
          <input value={editHostname} onChange={(e) => setEditHostname(e.target.value)} style={inputStyle} />
        </div>
      ) : (
        <h3 style={{
          color: 'var(--text-code)', fontSize: 15, fontWeight: 600,
          marginBottom: 22, fontFamily: 'var(--font-mono)',
        }}>
          <HighlightText text={asset.asset} spans={hostnameHls} />
        </h3>
      )}

      {/* Matched fields summary (shown when search highlights are present for non-inline fields) */}
      {matchedFieldSummary.length > 0 && (
        <div style={{ ...sectionStyle, background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)', padding: 12 }}>
          <div style={labelStyle}>Search Matches</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {matchedFieldSummary.map((hl, idx) => (
              <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <span style={{
                  background: 'var(--status-warning-bg, rgba(255,165,0,0.12))',
                  color: 'var(--status-warning, #f90)',
                  border: '1px solid var(--status-warning-border, rgba(255,165,0,0.3))',
                  borderRadius: 'var(--radius-sm)', padding: '1px 6px', fontSize: 10,
                  fontFamily: 'var(--font-mono)', fontWeight: 600, flexShrink: 0,
                }}>
                  {hl.field === 'vuln' ? `vuln → ${hl.source}` : hl.field}
                </span>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  <HighlightText text={hl.snippet} spans={[{ start: hl.start, end: hl.end }]} />
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Metadata */}
      <div style={sectionStyle}>
        <div style={labelStyle}>Metadata</div>
        {editing ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div>
              <div style={fieldLabel}>Type</div>
              <select value={editType} onChange={(e) => setEditType(e.target.value as 'subdomain' | 'ip')} style={{ ...inputStyle, cursor: 'pointer' }}>
                <option value="subdomain">subdomain</option>
                <option value="ip">ip</option>
              </select>
            </div>
            <div>
              <div style={fieldLabel}>Status Code</div>
              <input value={editStatus} onChange={(e) => setEditStatus(e.target.value)} style={inputStyle} placeholder="e.g. 200" type="number" />
            </div>
            <div>
              <div style={fieldLabel}>Title</div>
              <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} style={inputStyle} placeholder="Page title" />
            </div>
            <div>
              <div style={fieldLabel}>Content Length</div>
              <input value={editLength} onChange={(e) => setEditLength(e.target.value)} style={inputStyle} placeholder="e.g. 12345" type="number" />
            </div>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 13 }}>
            <div>
              <span style={{ color: 'var(--text-muted)', fontSize: 11}}>Type</span>
              <div style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: 12, marginTop: 2 }}>{asset.asset_type}</div>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', fontSize: 11}}>Status</span>
              <div style={{
                fontFamily: 'var(--font-mono)', color: statusColor(asset.status_code),
                fontWeight: 600, fontSize: 12, marginTop: 2,
              }}>
                {asset.status_code ?? 'N/A'}
              </div>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', fontSize: 11}}>Title</span>
              <div style={{ color: 'var(--text-primary)', fontSize: 12, marginTop: 2 }}>
                {asset.title ? <HighlightText text={asset.title} spans={titleHls} /> : 'N/A'}
              </div>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', fontSize: 11}}>Length</span>
              <div style={{ fontFamily: 'var(--font-mono)', color: '#c8c8c8', fontSize: 12, marginTop: 2 }}>
                {asset.content_length?.toLocaleString() ?? 'N/A'}
              </div>
            </div>
            {asset.redirects_to && (
              <div>
                <span style={{ color: 'var(--text-muted)', fontSize: 11}}>Redirects to</span>
                <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-primary)', fontSize: 12, marginTop: 2, wordBreak: 'break-all' }}>
                  {asset.redirects_to}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Technologies */}
      <div style={sectionStyle}>
        <div style={labelStyle}>Technologies</div>
        {editing ? (
          <div>
            <input value={editTech} onChange={(e) => setEditTech(e.target.value)} style={inputStyle}
              placeholder="Comma-separated, e.g. nginx, React, jQuery"
            />
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>Comma-separated list</div>
          </div>
        ) : (
          asset.technologies.length > 0 ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
              {asset.technologies.map((t, idx) => {
                const spans = techHls.filter((h) => h.index === idx);
                return (
                  <span key={t} style={{
                    background: 'var(--accent-subtle)',
                    color: 'var(--accent-primary)',
                    border: spans.length > 0 ? '1px solid var(--accent-primary)' : '1px solid var(--accent-border)',
                    borderRadius: 'var(--radius-sm)', padding: '3px 8px', fontSize: 11,
                    fontFamily: 'var(--font-mono)', fontWeight: 500,
                  }}>
                    <HighlightText text={t} spans={spans} />
                  </span>
                );
              })}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>None</div>
          )
        )}
      </div>

      {/* DNS Records */}
      <div style={sectionStyle}>
        <div style={labelStyle}>DNS Records</div>
        {editing ? (
          <div>
            <textarea value={editDns} onChange={(e) => setEditDns(e.target.value)}
              rows={4}
              style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.5, fontSize: 11 }}
              placeholder='[{"type": "A", "value": "1.2.3.4"}]'
            />
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>JSON array</div>
          </div>
        ) : (
          asset.dns_records.length > 0 ? (
            <pre style={{ ...codeBlockStyle, maxHeight: 140 }}>
              {JSON.stringify(asset.dns_records, null, 2)}
            </pre>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>None</div>
          )
        )}
      </div>

      {/* Crawled URLs */}
      <div style={sectionStyle}>
        <div style={labelStyle}>Crawled URLs {!editing && asset.crawled_urls.length > 0 && `(${asset.crawled_urls.length})`}</div>
        {editing ? (
          <div>
            <textarea value={editUrls} onChange={(e) => setEditUrls(e.target.value)}
              rows={4}
              style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.5, fontSize: 11 }}
              placeholder={"https://example.com/path1\nhttps://example.com/path2"}
            />
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>One URL per line</div>
          </div>
        ) : (
          asset.crawled_urls.length > 0 ? (
            <div style={{ ...codeBlockStyle, maxHeight: 200 }}>
              {asset.crawled_urls.map((url, i) => {
                const spans = urlHls.filter((h) => h.index === i);
                return (
                  <div key={i} style={{ color: 'var(--text-secondary)', opacity: 0.9 }}>
                    <HighlightText text={url} spans={spans} />
                  </div>
                );
              })}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>None</div>
          )
        )}
      </div>

      {/* Screenshot (read-only) */}
      {screenshotUrl && (
        <div style={sectionStyle}>
          <div style={labelStyle}>Screenshot</div>
          <a href={screenshotUrl} target="_blank" rel="noopener noreferrer">
            <img
              src={screenshotUrl}
              alt={`Screenshot of ${asset.asset}`}
              style={{
                width: '100%', borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)', display: 'block',
                background: 'var(--bg-void)',
              }}
            />
          </a>
        </div>
      )}

      {/* Response File (read-only) */}
      {fileContent && (
        <div style={sectionStyle}>
          <div style={labelStyle}>Response File</div>
          <pre style={{ ...codeBlockStyle, maxHeight: 300, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            <HighlightText text={fileContent} spans={fileSpans} />
          </pre>
        </div>
      )}

      {/* Findings */}
      <div style={{ paddingBottom: 8 }}>
        <FindingsPanel projectId={asset.project_id} assetId={asset.id} />
      </div>
    </div>
  );
}
