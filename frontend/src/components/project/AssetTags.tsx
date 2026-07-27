// frontend/src/components/project/AssetTags.tsx
import React, { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import type { Asset, Highlight } from '../../types/asset';
import type { TagWithCount } from '../../types/tag';
import { NEW_TAG_LABEL } from '../../types/tag';
import { attachTag, detachTag, fetchTags } from '../../api/tags';
import TagChip, { orderTags } from '../shared/TagChip';

interface Props {
  asset: Asset;
  highlights?: Highlight[];
  isAdmin: boolean;
  /** Called with the updated asset after a tag is attached or detached. */
  onTagsChanged?: (asset: Asset) => void;
}

function errorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

/**
 * Full tag list for one asset plus the entry field.
 *
 * Only user tags are removable: discovery-source tags are read-only, and the
 * server enforces that independently of what this component renders. "New!" is
 * derived and so has no chip affordance at all.
 */
export default function AssetTags({ asset, highlights, isAdmin, onTagsChanged }: Props) {
  const [entry, setEntry] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [suggestions, setSuggestions] = useState<TagWithCount[]>([]);

  // Keyed on the tag ids rather than the array: a refetch hands back a new
  // array identity for an unchanged tag set, which would re-request the
  // suggestions after every mutation.
  const tagKey = (asset.tags || []).map((t) => t.id).join(',');

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    fetchTags(asset.project_id)
      .then((tags) => { if (!cancelled) setSuggestions(tags); })
      .catch(() => { /* suggestions are optional — the field still works */ });
    return () => { cancelled = true; };
  }, [asset.project_id, isAdmin, tagKey]);

  const tagHls = (highlights || []).filter((h) => h.source === 'tag');
  const ordered = orderTags(asset.tags || []);

  const runChange = async (fn: () => Promise<Asset>, fallbackMsg: string) => {
    setBusy(true);
    setError('');
    try {
      onTagsChanged?.(await fn());
      return true;
    } catch (err) {
      setError(errorMessage(err, fallbackMsg));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = entry.trim();
    if (!name || busy) return;
    const ok = await runChange(
      () => attachTag(asset.project_id, asset.id, { name }),
      'Could not add tag',
    );
    // A rejected add (duplicate name, bad characters) leaves the field intact
    // so the operator can correct it instead of retyping.
    if (ok) setEntry('');
  };

  // Guarded like the add path: two quick clicks on a chip's X would otherwise
  // fire concurrent deletes whose responses race, and the losing one can put
  // the removed tag back on screen.
  const handleRemove = (tagId: string) => {
    if (busy) return;
    return runChange(() => detachTag(asset.project_id, asset.id, tagId), 'Could not remove tag');
  };

  // Offer only tags the asset does not already carry, and never system tags.
  const assigned = new Set((asset.tags || []).map((t) => t.id));
  const available = suggestions.filter((t) => !t.is_system && !assigned.has(t.id));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
        {asset.is_new && (
          <TagChip
            label={NEW_TAG_LABEL}
            variant="new"
            title="First seen by the most recent recon scan"
            spans={tagHls.filter((h) => h.snippet === NEW_TAG_LABEL)}
          />
        )}
        {ordered.map((tag) => (
          <TagChip
            key={tag.id}
            label={tag.name}
            variant={tag.is_system ? 'system' : 'user'}
            color={tag.color}
            title={tag.is_system ? `Discovery source: ${tag.name}` : tag.name}
            spans={tagHls.filter((h) => h.snippet === tag.name)}
            onRemove={isAdmin && !tag.is_system ? () => handleRemove(tag.id) : undefined}
          />
        ))}
        {!asset.is_new && ordered.length === 0 && (
          <span style={{ color: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
            No tags
          </span>
        )}
      </div>

      {isAdmin && (
        <form onSubmit={handleAdd} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            list={`tag-suggestions-${asset.id}`}
            placeholder="Add a tag…"
            maxLength={40}
            disabled={busy}
            style={{
              flex: 1, background: 'var(--bg-void)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
              padding: '4px 8px', fontSize: 11, fontFamily: 'var(--font-mono)',
            }}
          />
          <datalist id={`tag-suggestions-${asset.id}`}>
            {available.map((t) => <option key={t.id} value={t.name} />)}
          </datalist>
          <button
            type="submit"
            disabled={busy || !entry.trim()}
            className="btn-secondary"
            style={{
              padding: '4px 10px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4,
              opacity: busy || !entry.trim() ? 0.5 : 1,
            }}
          >
            <Plus size={11} /> Add
          </button>
        </form>
      )}

      {error && (
        <div style={{
          color: 'var(--status-error)', fontSize: 10, fontFamily: 'var(--font-mono)',
        }}>{error}</div>
      )}
    </div>
  );
}
