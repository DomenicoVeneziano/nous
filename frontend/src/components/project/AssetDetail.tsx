// frontend/src/components/project/AssetDetail.tsx
import React, { useEffect, useState } from 'react';
import { X, Pencil, Trash2, Save, RotateCcw, Copy, Check, Download } from 'lucide-react';
import type { Asset, AssetUpdate, Highlight } from '../../types/asset';
import { HighlightText } from '../shared/HighlightText';
import { updateAsset, deleteAsset, fetchImageObjectUrl, exportAsset } from '../../api/assets';
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

type DnsRecord = Record<string, unknown>;

function dnsRecordType(rec: DnsRecord): string {
  return rec.type != null ? String(rec.type) : '—';
}

/** Human-readable value for a single DNS record, folding in type-specific extras. */
function formatDnsValue(rec: DnsRecord): string {
  const value = rec.value != null ? String(rec.value) : '';
  if (rec.type === 'MX' && rec.preference != null) {
    return `${value}  ·  pref ${rec.preference}`;
  }
  if (rec.type === 'SOA' && rec.serial != null) {
    return `${value}  ·  serial ${rec.serial}`;
  }
  return value;
}

/**
 * Normalize stored DNS records to a flat list of {type, value, ...} records.
 * Recon scans store records flat, but older scans wrapped them per resolver as
 * [{resolver, records: [...]}]. Expand any such envelopes and drop cross-scan
 * duplicates so both shapes render correctly.
 */
function flattenDnsRecords(records: DnsRecord[]): DnsRecord[] {
  const flat: DnsRecord[] = [];
  const seen = new Set<string>();
  for (const rec of records) {
    const inner = Array.isArray(rec.records) ? (rec.records as DnsRecord[]) : [rec];
    for (const r of inner) {
      const key = `${r.type ?? ''}|${r.value ?? ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      flat.push(r);
    }
  }
  return flat;
}

const dnsBadgeStyle: React.CSSProperties = {
  flexShrink: 0, width: 48, textAlign: 'center',
  background: 'var(--accent-subtle)', color: 'var(--accent-primary)',
  border: '1px solid var(--accent-border)', borderRadius: 'var(--radius-sm)',
  padding: '2px 0', fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 600,
  letterSpacing: '0.04em',
};

const codeBlockStyle: React.CSSProperties = {
  background: 'var(--bg-void)', border: '1px solid var(--border-subtle)',
  borderRadius: 'var(--radius-md)', padding: 14, fontSize: 11, fontFamily: 'var(--font-mono)',
  color: 'var(--text-code)', overflow: 'auto', lineHeight: 1.6,
};

// Raw HTTP responses can be hundreds of KB. A text node that large with
// pre-wrap + break-all is pathologically slow to lay out, and — because it
// shares the detail panel's layout — it makes unrelated interactions (typing in
// the findings form below it) janky. Render a bounded preview by default and
// let the user expand to the full body on demand.
const RESPONSE_PREVIEW_LIMIT = 30000;

function ResponseFileView({ content, spans }: { content: string; spans: { start: number; end: number }[] }) {
  const [full, setFull] = useState(false);
  // Never hide a search match: if a highlight lands past the preview, show it all.
  const spansPastPreview = spans.some((s) => s.end > RESPONSE_PREVIEW_LIMIT);
  const truncated = !full && !spansPastPreview && content.length > RESPONSE_PREVIEW_LIMIT;
  const shown = truncated ? content.slice(0, RESPONSE_PREVIEW_LIMIT) : content;
  const shownSpans = truncated ? spans.filter((s) => s.start < RESPONSE_PREVIEW_LIMIT) : spans;

  return (
    <>
      <pre style={{
        ...codeBlockStyle, maxHeight: 300, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
        contentVisibility: 'auto', containIntrinsicSize: 'auto 300px',
      }}>
        <HighlightText text={shown} spans={shownSpans} />
      </pre>
      {truncated && (
        <button
          onClick={() => setFull(true)}
          style={{
            width: '100%', marginTop: 6, background: 'var(--bg-elevated)', border: 'none',
            borderRadius: 'var(--radius-sm)', color: 'var(--accent-primary)',
            padding: '7px 12px', fontSize: 11, fontFamily: 'var(--font-mono)', cursor: 'pointer',
          }}
        >
          Show full response ({Math.round(content.length / 1024).toLocaleString()} KB)
        </button>
      )}
    </>
  );
}

// How many endpoint rows to mount initially, and how many more per "show more".
// Assets can carry tens of thousands of archived URLs; mounting them all at once
// freezes the panel for seconds (worst on remount, e.g. leaving edit mode), so
// we render a bounded window and let the user expand it on demand.
const URL_WINDOW = 200;

/** Scrollable, windowed list of endpoint URLs with search-highlight support. */
function UrlList({ urls, highlights }: { urls: string[]; highlights: Highlight[] }) {
  const [visible, setVisible] = useState(URL_WINDOW);
  // Collapse back to the first window whenever the underlying list changes
  // (e.g. switching to a different asset).
  useEffect(() => { setVisible(URL_WINDOW); }, [urls]);

  const shown = urls.slice(0, visible);
  const remaining = urls.length - shown.length;

  return (
    <div style={{
      background: 'var(--bg-void)', border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-md)', maxHeight: 220, overflow: 'auto',
    }}>
      {shown.map((url, i) => {
        const spans = highlights.filter((h) => h.snippet === url);
        return (
          <div key={i} style={{
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)',
            padding: '5px 12px', lineHeight: 1.5, wordBreak: 'break-all',
            borderTop: i > 0 ? '1px solid var(--border-subtle)' : 'none',
            contentVisibility: 'auto', containIntrinsicSize: 'auto 22px',
          }}>
            <HighlightText text={url} spans={spans} />
          </div>
        );
      })}
      {remaining > 0 && (
        <button
          onClick={() => setVisible((v) => v + URL_WINDOW * 5)}
          style={{
            width: '100%', background: 'var(--bg-elevated)', border: 'none',
            borderTop: '1px solid var(--border-subtle)', color: 'var(--accent-primary)',
            padding: '7px 12px', fontSize: 11, fontFamily: 'var(--font-mono)', cursor: 'pointer',
          }}
        >
          Show {Math.min(URL_WINDOW * 5, remaining).toLocaleString()} more
          {' '}({remaining.toLocaleString()} hidden)
        </button>
      )}
    </div>
  );
}

/**
 * Copy text to the clipboard, returning whether it succeeded.
 * navigator.clipboard only exists in secure contexts (HTTPS/localhost); this app
 * is frequently served over plain HTTP on a LAN IP, so fall back to the legacy
 * execCommand path there.
 */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (window.isSecureContext && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-9999px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/** Icon button that copies `text` to the clipboard, briefly showing a check on success. */
function CopyButton({ text, title = 'Copy', size = 13, style }: {
  text: string; title?: string; size?: number; style?: React.CSSProperties;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (await copyToClipboard(text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    }
  };
  return (
    <button
      onClick={copy}
      title={copied ? 'Copied' : title}
      aria-label={title}
      style={{
        flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'transparent', border: 'none', cursor: 'pointer',
        padding: 3, borderRadius: 'var(--radius-sm)',
        color: copied ? 'var(--status-success)' : 'var(--text-muted)',
        transition: 'color var(--transition-fast)',
        ...style,
      }}
    >
      {copied ? <Check size={size} /> : <Copy size={size} />}
    </button>
  );
}

/** One DNS record as a Type / Value / copy-action row. The copy button reveals on hover. */
function DnsRow({ rec, divider }: { rec: DnsRecord; divider: boolean }) {
  const [hover, setHover] = useState(false);
  const [copied, setCopied] = useState(false);
  const copyValue = rec.value != null ? String(rec.value) : formatDnsValue(rec);

  const copy = async () => {
    if (await copyToClipboard(copyValue)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    }
  };

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '5px 4px',
        borderTop: divider ? '1px solid var(--border-subtle)' : 'none',
        contentVisibility: 'auto', containIntrinsicSize: 'auto 30px',
      }}
    >
      <span style={dnsBadgeStyle}>{dnsRecordType(rec)}</span>
      <span style={{
        flex: 1, minWidth: 0, fontFamily: 'var(--font-mono)', fontSize: 12,
        color: 'var(--text-code)', wordBreak: 'break-all', lineHeight: 1.45,
      }}>
        {formatDnsValue(rec)}
      </span>
      <button
        onClick={copy}
        title={copied ? 'Copied' : 'Copy value'}
        aria-label="Copy value"
        style={{
          flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'transparent', border: 'none', cursor: 'pointer',
          padding: 4, borderRadius: 'var(--radius-sm)',
          color: copied ? 'var(--status-success)' : 'var(--text-muted)',
          opacity: hover || copied ? 1 : 0,
          transition: 'opacity var(--transition-fast), color var(--transition-fast)',
        }}
      >
        {copied ? <Check size={13} /> : <Copy size={13} />}
      </button>
    </div>
  );
}

export default function AssetDetail({ asset, highlights, onClose, onAssetUpdated, onAssetDeleted }: Props) {
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const { isAdmin } = useAuth();

  const [editHostname, setEditHostname] = useState('');
  const [editType, setEditType] = useState<'subdomain' | 'ip'>('subdomain');
  const [editStatus, setEditStatus] = useState('');
  const [editTitle, setEditTitle] = useState('');
  const [editLength, setEditLength] = useState('');
  const [editTech, setEditTech] = useState('');
  const [editDns, setEditDns] = useState('');
  const [editCrawling, setEditCrawling] = useState('');
  const [editArchived, setEditArchived] = useState('');

  useEffect(() => {
    if (asset?.response_file_path) {
      // response_file_path is stored relative to the data dir (e.g.
      // "projects/<id>/responses/<host>.txt"), but /files/content resolves
      // paths relative to data/projects/. Strip the leading "projects/" so the
      // file isn't looked up under a doubled "projects/projects/..." path.
      const relPath = asset.response_file_path.replace(/^projects\//, '');
      client.get('/files/content', {
        params: { path: relPath },
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

  const dnsRecords = flattenDnsRecords(asset.dns_records);

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
    setEditDns(dnsRecords.length > 0 ? JSON.stringify(dnsRecords, null, 2) : '');
    setEditCrawling(asset.crawled_urls.crawling.join('\n'));
    setEditArchived(asset.crawled_urls.archived.join('\n'));
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
          if (JSON.stringify(parsed) !== JSON.stringify(dnsRecords)) payload.dns_records = parsed;
        } catch {
          setError('Invalid JSON in DNS records');
          setSaving(false);
          return;
        }
      } else if (dnsRecords.length > 0) {
        payload.dns_records = [];
      }
      // Dedup each section independently so manually pasted lines never
      // produce duplicates within a source.
      const dedup = (raw: string) => Array.from(
        new Set(raw.split('\n').map((u) => u.trim()).filter(Boolean))
      );
      const newCrawledUrls = { crawling: dedup(editCrawling), archived: dedup(editArchived) };
      if (JSON.stringify(newCrawledUrls) !== JSON.stringify(asset.crawled_urls)) {
        payload.crawled_urls = newCrawledUrls;
      }
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

  const handleExport = async () => {
    setExporting(true);
    setError('');
    try {
      await exportAsset(asset.project_id, asset.id, asset.asset);
    } catch {
      setError('Failed to export');
    } finally {
      setExporting(false);
    }
  };

  const sectionStyle: React.CSSProperties = {
    marginBottom: 18, paddingBottom: 18, borderBottom: '1px solid var(--border-subtle)',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
    letterSpacing: '0.08em', marginBottom: 8,
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

  // Render one source-specific endpoint section (view + inline edit). Search
  // highlights are matched to a row by snippet text so they resolve regardless
  // of which section the URL lives in.
  const renderUrlSection = (
    label: string,
    urls: string[],
    editValue: string,
    onEditChange: (v: string) => void,
  ) => (
    <div style={sectionStyle}>
      <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span>{label} {!editing && urls.length > 0 && `(${urls.length})`}</span>
        {!editing && urls.length > 0 && (
          <CopyButton text={urls.join('\n')} title={`Copy all ${label.toLowerCase()}`} />
        )}
      </div>
      {editing ? (
        <div>
          <textarea value={editValue} onChange={(e) => onEditChange(e.target.value)}
            rows={4}
            style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.5, fontSize: 11 }}
            placeholder={"/path1\n/path2"}
          />
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>
            One URL per line — duplicates are removed automatically
          </div>
        </div>
      ) : (
        urls.length > 0 ? (
          <UrlList urls={urls} highlights={urlHls} />
        ) : (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>None</div>
        )
      )}
    </div>
  );

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
          {!editing && (
            <button onClick={handleExport} disabled={exporting} className="btn-secondary" style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Download size={11} /> {exporting ? 'Exporting...' : 'Export'}
            </button>
          )}
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
          dnsRecords.length > 0 ? (
            <div style={{
              background: 'var(--bg-void)', border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)', padding: '4px 8px', maxHeight: 200, overflow: 'auto',
            }}>
              {dnsRecords.map((rec, i) => (
                <DnsRow key={i} rec={rec} divider={i > 0} />
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>None</div>
          )
        )}
      </div>

      {/* Endpoints, separated by source */}
      {renderUrlSection('Crawled Endpoints', asset.crawled_urls.crawling, editCrawling, setEditCrawling)}
      {renderUrlSection('Archived Endpoints', asset.crawled_urls.archived, editArchived, setEditArchived)}

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
          <ResponseFileView content={fileContent} spans={fileSpans} />
        </div>
      )}

      {/* Findings */}
      <div style={{ paddingBottom: 8 }}>
        <FindingsPanel projectId={asset.project_id} assetId={asset.id} />
      </div>
    </div>
  );
}
