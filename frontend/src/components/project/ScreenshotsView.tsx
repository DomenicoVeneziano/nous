// frontend/src/components/project/ScreenshotsView.tsx
import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { X, ChevronLeft, ChevronRight, ImageOff, Camera, Trash2, Check } from 'lucide-react';
import type { Asset } from '../../types/asset';
import { fetchImageObjectUrl, deleteAssetScreenshot } from '../../api/assets';
import { useAuth } from '../../hooks/useAuth';

interface Props {
  assets: Asset[];
  projectId: string;
  onChanged?: () => void;
}

/**
 * Loads a project image as an authenticated blob and renders it, managing the
 * object-URL lifecycle (revoked on unmount / path change to avoid leaks).
 */
function ScreenshotImage({
  path,
  style,
  alt,
}: {
  path: string;
  style: React.CSSProperties;
  alt: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    fetchImageObjectUrl(path)
      .then((u) => {
        if (active) {
          objectUrl = u;
          setUrl(u);
        } else {
          URL.revokeObjectURL(u);
        }
      })
      .catch(() => { if (active) setFailed(true); });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (failed) {
    return (
      <div style={{
        ...style, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg-void)', color: 'var(--text-muted)',
      }}>
        <ImageOff size={20} />
      </div>
    );
  }

  if (!url) {
    return (
      <div style={{
        ...style, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg-void)', color: 'var(--text-muted)', fontSize: 11,
        fontFamily: 'var(--font-mono)',
      }}>
        Loading…
      </div>
    );
  }

  return <img src={url} alt={alt} style={style} />;
}

export default function ScreenshotsView({ assets, projectId, onChanged }: Props) {
  const { isAdmin } = useAuth();
  const shots = useMemo(
    () => assets.filter((a) => !!a.screenshot_path),
    [assets],
  );
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [lbConfirm, setLbConfirm] = useState(false);

  const close = useCallback(() => { setLightboxIdx(null); setLbConfirm(false); }, []);
  const prev = useCallback(
    () => { setLbConfirm(false); setLightboxIdx((i) => (i === null ? i : (i - 1 + shots.length) % shots.length)); },
    [shots.length],
  );
  const next = useCallback(
    () => { setLbConfirm(false); setLightboxIdx((i) => (i === null ? i : (i + 1) % shots.length)); },
    [shots.length],
  );

  useEffect(() => {
    if (lightboxIdx === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') prev();
      else if (e.key === 'ArrowRight') next();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightboxIdx, close, prev, next]);

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const nextSet = new Set(prev);
      if (nextSet.has(id)) nextSet.delete(id); else nextSet.add(id);
      return nextSet;
    });
  }, []);

  const clearSelection = useCallback(() => { setSelected(new Set()); setBulkConfirm(false); }, []);

  const deleteScreenshots = useCallback(async (ids: string[]) => {
    if (ids.length === 0) return;
    setDeleting(true);
    try {
      await Promise.allSettled(ids.map((id) => deleteAssetScreenshot(projectId, id)));
      onChanged?.();
    } finally {
      setDeleting(false);
    }
  }, [projectId, onChanged]);

  if (shots.length === 0) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        gap: 12, padding: '64px 24px', color: 'var(--text-muted)', textAlign: 'center',
      }}>
        <Camera size={28} />
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)' }}>
          No screenshots yet
        </div>
        <div style={{ fontSize: 12, maxWidth: 420, lineHeight: 1.6 }}>
          Enable <span style={{ fontFamily: 'var(--font-mono)' }}>Take Screenshots</span> in
          Settings → Scan Config, then run a Technology Analysis scan to capture a screenshot
          of each asset.
        </div>
      </div>
    );
  }

  const active = lightboxIdx !== null ? shots[lightboxIdx] : null;

  const labelStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-primary)',
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  };

  const allSelected = selected.size === shots.length && shots.length > 0;

  return (
    <div>
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
        fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: 14,
        minHeight: 30,
      }}>
        <span>
          {shots.length} screenshot{shots.length === 1 ? '' : 's'}
          {selected.size > 0 ? ` · ${selected.size} selected` : ''}
        </span>
        {isAdmin && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              onClick={() => (allSelected ? clearSelection() : setSelected(new Set(shots.map((s) => s.id))))}
              className="btn-secondary"
              style={{ padding: '4px 10px', fontSize: 11 }}
            >
              {allSelected ? 'Clear' : 'Select all'}
            </button>
            {selected.size > 0 && (
              bulkConfirm ? (
                <>
                  <span style={{ color: 'var(--text-secondary)' }}>Delete {selected.size}?</span>
                  <button
                    onClick={() => deleteScreenshots([...selected]).then(clearSelection)}
                    disabled={deleting}
                    className="btn-primary"
                    style={{ padding: '4px 10px', fontSize: 11, background: 'var(--error, #d9534f)', borderColor: 'transparent' }}
                  >
                    {deleting ? 'Deleting…' : 'Confirm'}
                  </button>
                  <button onClick={() => setBulkConfirm(false)} className="btn-secondary" style={{ padding: '4px 10px', fontSize: 11 }}>
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  onClick={() => setBulkConfirm(true)}
                  disabled={deleting}
                  className="btn-secondary"
                  style={{ padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 5, color: 'var(--error, #e06c6c)' }}
                >
                  <Trash2 size={12} /> Delete ({selected.size})
                </button>
              )
            )}
          </div>
        )}
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14,
      }}>
        {shots.map((a, idx) => {
          const isSel = selected.has(a.id);
          return (
            <div
              key={a.id}
              onClick={() => setLightboxIdx(idx)}
              style={{
                background: 'var(--bg-surface)',
                border: `1px solid ${isSel ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
                borderRadius: 8, overflow: 'hidden', cursor: 'pointer', position: 'relative',
                transition: 'border-color var(--transition-fast), transform var(--transition-fast)',
              }}
              onMouseEnter={(e) => { if (!isSel) e.currentTarget.style.borderColor = 'var(--accent-border)'; e.currentTarget.style.transform = 'translateY(-2px)'; }}
              onMouseLeave={(e) => { if (!isSel) e.currentTarget.style.borderColor = 'var(--border-subtle)'; e.currentTarget.style.transform = 'none'; }}
            >
              {isAdmin && (
                <button
                  onClick={(e) => { e.stopPropagation(); toggleSelect(a.id); }}
                  title={isSel ? 'Deselect' : 'Select'}
                  style={{
                    position: 'absolute', top: 8, left: 8, zIndex: 2,
                    width: 22, height: 22, borderRadius: 5, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: isSel ? 'var(--accent-primary)' : 'rgba(0,0,0,0.55)',
                    border: `1px solid ${isSel ? 'var(--accent-primary)' : 'rgba(255,255,255,0.4)'}`,
                    color: isSel ? 'var(--bg-base, #0b0b0f)' : '#fff',
                  }}
                >
                  {isSel && <Check size={14} strokeWidth={3} />}
                </button>
              )}
              <ScreenshotImage
                path={a.screenshot_path as string}
                alt={a.asset}
                style={{
                  width: '100%', aspectRatio: '16 / 10', objectFit: 'cover',
                  objectPosition: 'top', display: 'block', background: 'var(--bg-void)',
                }}
              />
              <div style={{
                padding: '8px 10px', borderTop: '1px solid var(--border-subtle)',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
              }}>
                <span style={labelStyle}>{a.asset}</span>
                {a.status_code != null && (
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
                    color: 'var(--text-muted)', flexShrink: 0,
                  }}>{a.status_code}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Lightbox / slideshow */}
      {active && (
        <div
          onClick={close}
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.86)', backdropFilter: 'blur(4px)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            padding: 24,
          }}
        >
          {/* Header */}
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              width: '100%', maxWidth: '92vw', marginBottom: 12,
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--text-primary)', fontWeight: 600 }}>
                {active.asset}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                {(lightboxIdx ?? 0) + 1} / {shots.length}
                {active.title ? ` · ${active.title}` : ''}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {isAdmin && (
                lbConfirm ? (
                  <>
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Delete?</span>
                    <button
                      onClick={() => {
                        const id = active.id;
                        deleteScreenshots([id]).then(() => {
                          setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
                          close();
                        });
                      }}
                      disabled={deleting}
                      style={{
                        background: 'var(--error, #d9534f)', border: '1px solid transparent', borderRadius: 6,
                        color: '#000', padding: '6px 10px', cursor: 'pointer', fontSize: 12,
                      }}
                    >
                      {deleting ? 'Deleting…' : 'Confirm'}
                    </button>
                    <button
                      onClick={() => setLbConfirm(false)}
                      style={{
                        background: 'transparent', border: '1px solid var(--border-default)', borderRadius: 6,
                        color: 'var(--text-secondary)', padding: '6px 10px', cursor: 'pointer', fontSize: 12,
                      }}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => setLbConfirm(true)}
                    title="Delete screenshot"
                    style={{
                      background: 'transparent', border: '1px solid var(--border-default)', borderRadius: 6,
                      color: 'var(--error, #e06c6c)', padding: 6, cursor: 'pointer', display: 'flex',
                    }}
                  >
                    <Trash2 size={18} />
                  </button>
                )
              )}
              <button
                onClick={close}
                style={{
                  background: 'transparent', border: '1px solid var(--border-default)', borderRadius: 6,
                  color: 'var(--text-secondary)', padding: 6, cursor: 'pointer', display: 'flex',
                }}
              >
                <X size={18} />
              </button>
            </div>
          </div>

          {/* Image + nav */}
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ display: 'flex', alignItems: 'center', gap: 12, maxWidth: '92vw' }}
          >
            <button onClick={prev} disabled={shots.length < 2} style={navBtnStyle}>
              <ChevronLeft size={22} />
            </button>
            <ScreenshotImage
              path={active.screenshot_path as string}
              alt={active.asset}
              style={{
                maxWidth: '80vw', maxHeight: '82vh', objectFit: 'contain',
                borderRadius: 8, border: '1px solid var(--border-subtle)',
                background: 'var(--bg-void)', display: 'block',
              }}
            />
            <button onClick={next} disabled={shots.length < 2} style={navBtnStyle}>
              <ChevronRight size={22} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const navBtnStyle: React.CSSProperties = {
  background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: '50%',
  color: 'var(--text-secondary)', width: 40, height: 40, flexShrink: 0,
  display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
};
