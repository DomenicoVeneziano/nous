// frontend/src/components/shared/TagChip.tsx
import React from 'react';
import { X } from 'lucide-react';
import type { Tag } from '../../types/tag';
import { HighlightText } from './HighlightText';

type Variant = 'new' | 'system' | 'user';

/**
 * Three visual weights, so a dense row still reads at a glance:
 *   new    — inverted fill, the loudest thing in the row
 *   user   — subtle fill, the labels the operator curates
 *   system — outline only, provenance that should recede
 * A user tag with a custom colour overrides the fill; everything else stays on
 * the monochrome palette.
 */
function variantStyle(variant: Variant, color: string | null): React.CSSProperties {
  if (variant === 'new') {
    return {
      background: 'var(--accent-primary)',
      color: 'var(--text-inverted)',
      border: '1px solid var(--accent-primary)',
      fontWeight: 700,
    };
  }
  if (variant === 'system') {
    return {
      background: 'transparent',
      color: 'var(--text-muted)',
      border: '1px dashed var(--border-default)',
      fontWeight: 500,
    };
  }
  if (color) {
    return {
      background: `${color}1f`,
      color,
      border: `1px solid ${color}59`,
      fontWeight: 600,
    };
  }
  return {
    background: 'var(--accent-subtle)',
    color: 'var(--text-primary)',
    border: '1px solid var(--accent-border)',
    fontWeight: 600,
  };
}

interface Props {
  label: string;
  variant: Variant;
  color?: string | null;
  title?: string;
  /** Search-match spans within `label`, highlighted in place. */
  spans?: { start: number; end: number }[];
  onRemove?: () => void;
}

export default function TagChip({ label, variant, color = null, title, spans, onRemove }: Props) {
  return (
    <span
      title={title}
      style={{
        ...variantStyle(variant, color),
        display: 'inline-flex', alignItems: 'center', gap: 4,
        borderRadius: 'var(--radius-sm)', padding: '1px 6px', fontSize: 10,
        fontFamily: 'var(--font-mono)', lineHeight: 1.6, whiteSpace: 'nowrap',
      }}
    >
      {spans && spans.length > 0 ? <HighlightText text={label} spans={spans} /> : label}
      {onRemove && (
        <button
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          aria-label={`Remove tag ${label}`}
          style={{
            background: 'transparent', border: 'none', padding: 0, margin: 0,
            cursor: 'pointer', color: 'inherit', display: 'flex', alignItems: 'center',
            opacity: 0.6,
          }}
          onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; }}
          onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.6'; }}
        >
          <X size={9} />
        </button>
      )}
    </span>
  );
}

/**
 * Reading order: "New!" (rendered separately), then discovery sources, then the
 * operator's own labels.
 *
 * Sources lead because they are the at-a-glance signal — an asset found by
 * bruteforce *and* passive enumeration is worth noticing from the table — and
 * because the row caps its chips, whatever sorts last is what gets collapsed
 * into "+n tags". Swap the comparison to put user labels first.
 */
export function orderTags(tags: Tag[]): Tag[] {
  return [...tags].sort((a, b) => {
    if (a.is_system !== b.is_system) return a.is_system ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
}
