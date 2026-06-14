// frontend/src/components/shared/HighlightText.tsx
import React from 'react';

interface Span { start: number; end: number }

/** Merge overlapping/adjacent spans and clamp them to [0, textLen). */
function mergeSpans(spans: Span[], textLen: number): Span[] {
  const clamped = spans
    .map((s) => ({ start: Math.max(0, s.start), end: Math.min(textLen, s.end) }))
    .filter((s) => s.start < s.end);
  if (clamped.length === 0) return [];
  clamped.sort((a, b) => a.start - b.start);
  const merged: Span[] = [{ ...clamped[0] }];
  for (let i = 1; i < clamped.length; i++) {
    const last = merged[merged.length - 1];
    if (clamped[i].start <= last.end) {
      last.end = Math.max(last.end, clamped[i].end);
    } else {
      merged.push({ ...clamped[i] });
    }
  }
  return merged;
}

interface Props {
  text: string;
  spans: Span[];
  markStyle?: React.CSSProperties;
}

/**
 * Renders `text` with `<mark>` elements wrapping the given spans.
 * Falls back to plain text when there are no spans.
 */
export function HighlightText({ text, spans, markStyle }: Props) {
  const merged = mergeSpans(spans, text.length);
  if (merged.length === 0) return <>{text}</>;

  const defaultMarkStyle: React.CSSProperties = {
    background: 'var(--highlight-bg, rgba(255, 213, 0, 0.35))',
    color: 'var(--highlight-fg, inherit)',
    borderRadius: 2,
    padding: '0 1px',
    ...markStyle,
  };

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (const { start, end } of merged) {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <mark key={start} style={defaultMarkStyle}>
        {text.slice(start, end)}
      </mark>
    );
    cursor = end;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}
