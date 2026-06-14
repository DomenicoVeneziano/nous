// frontend/src/components/project/SearchBar.tsx
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Search, Loader2, X } from 'lucide-react';
import ExportButton from '../shared/ExportButton';
import SearchHelpButton from '../shared/SearchHelpButton';
import { fetchVulnPatterns } from '../../api/vulnPatterns';
import type { VulnPattern } from '../../types/vulnPattern';

interface Props {
  value: string;
  onChange: (value: string) => void;
  projectId?: string;
  resultCount?: number;
  loading?: boolean;
}

const ASSET_SEARCH_SECTIONS = [
  {
    heading: 'Asset Fields',
    rows: [
      { label: 'hostname:',       desc: 'Asset hostname or IP' },
      { label: 'tech:',           desc: 'Detected technology (e.g. nginx, React)' },
      { label: 'status:',         desc: 'HTTP status code (e.g. 200, 404)' },
      { label: 'title:',          desc: 'Page title' },
      { label: 'type:',           desc: 'Asset type: subdomain or ip' },
      { label: 'date:',           desc: 'Scan date prefix (e.g. 2026-04)' },
      { label: 'content_length:', desc: 'Response size in bytes' },
      { label: 'dns:',            desc: 'DNS record content' },
      { label: 'url:',            desc: 'Crawled URL paths' },
    ],
  },
  {
    heading: 'Response File Fields (slow)',
    rows: [
      { label: 'content:',  desc: 'Full response (headers + body)' },
      { label: 'header:',   desc: 'HTTP response headers only' },
      { label: 'body:',     desc: 'HTML body only' },
    ],
  },
  {
    heading: 'Cross-entity Fields',
    rows: [
      { label: 'severity:', desc: 'Assets with findings of this severity (low/medium/high/critical)' },
      { label: 'vuln:',     desc: 'Named vulnerability pattern (e.g. vuln:api_keys)' },
    ],
  },
  {
    heading: 'Value Formats',
    rows: [
      { label: 'tech:nginx',        desc: 'Case-insensitive substring match' },
      { label: 'title:"login page"', desc: 'Quoted string (spaces allowed)' },
      { label: 'hostname:/^api\\./', desc: 'Regex enclosed in / … / (IGNORECASE)' },
    ],
  },
  {
    heading: 'Operators',
    rows: [
      { label: 'AND', desc: 'Both clauses must match (default)' },
      { label: 'OR',  desc: 'Either clause matches' },
      { label: 'NOT', desc: 'Excludes assets matching the next clause' },
      { label: 'XOR', desc: 'Exactly one of the two clauses matches' },
    ],
  },
];

const ASSET_SEARCH_EXAMPLES = [
  { query: 'tech:nginx AND status:200',              desc: 'Nginx assets returning 200' },
  { query: 'hostname:/^api\\./ AND tech:react',      desc: 'API subdomains running React' },
  { query: 'status:200 NOT tech:cloudflare',         desc: '200s not behind Cloudflare' },
  { query: 'type:ip AND severity:high',              desc: 'IP assets with high-severity findings' },
  { query: 'vuln:cors AND tech:nginx',               desc: 'Nginx assets with permissive CORS' },
  { query: 'url:/\\/api\\// AND vuln:api_keys',      desc: 'API paths with exposed keys' },
  { query: 'header:X-Powered-By AND type:subdomain', desc: 'Subdomains leaking server version' },
];

// Mirrors the backend tokenizer: respects "quoted" and /regex/ delimiters so
// AND/OR/NOT/XOR inside them are never treated as operator boundaries.

const OPERATORS = new Set(['AND', 'OR', 'NOT', 'XOR']);

interface Chip {
  field: string;
  value: string;
  op: string;
}

function tokenizeQuery(raw: string): string[] {
  const tokens: string[] = [];
  const buf: string[] = [];
  let bufHasColon = false;
  let i = 0;
  const n = raw.length;

  while (i < n) {
    const c = raw[i];

    // Quoted string: consume until closing "
    if (c === '"') {
      const j = raw.indexOf('"', i + 1);
      const end = j !== -1 ? j + 1 : n;
      buf.push(raw.slice(i, end));
      i = end;
      continue;
    }

    // Regex delimiter /…/: only when already inside a `field:` buffer
    if (c === '/' && bufHasColon) {
      const j = raw.indexOf('/', i + 1);
      const end = j !== -1 ? j + 1 : n;
      buf.push(raw.slice(i, end));
      i = end;
      continue;
    }

    // Stand-alone boolean operator?
    let matchedOp: string | null = null;
    for (const op of OPERATORS) {
      if (raw.startsWith(op, i)) {
        const after = i + op.length;
        const beforeOk = i === 0 || raw[i - 1] === ' ' || raw[i - 1] === '\t';
        const afterOk  = after >= n || raw[after] === ' ' || raw[after] === '\t';
        if (beforeOk && afterOk) { matchedOp = op; break; }
      }
    }

    if (matchedOp) {
      const clause = buf.join('').trim();
      if (clause) tokens.push(clause);
      buf.length = 0;
      bufHasColon = false;
      tokens.push(matchedOp);
      i += matchedOp.length;
      continue;
    }

    if (c === ':') bufHasColon = true;
    buf.push(c);
    i++;
  }

  const remaining = buf.join('').trim();
  if (remaining) tokens.push(remaining);
  return tokens;
}

function parseChips(query: string): Chip[] {
  const tokens = tokenizeQuery(query);
  const chips: Chip[] = [];
  let currentOp = 'AND';

  for (const token of tokens) {
    if (OPERATORS.has(token)) {
      currentOp = token;
      continue;
    }
    const colonIdx = token.indexOf(':');
    if (colonIdx > 0) {
      const field = token.slice(0, colonIdx);
      const value = token.slice(colonIdx + 1).trim();
      chips.push({ field, value, op: currentOp });
    }
    currentOp = 'AND';
  }
  return chips;
}

/** Rebuild query string after removing the chip at `removeIndex`. */
function removeChip(query: string, removeIndex: number): string {
  const tokens = tokenizeQuery(query);
  // Collect clause tokens with their preceding operator token indices
  const clauseEntries: { clauseIdx: number; opIdx: number | null }[] = [];
  for (let i = 0; i < tokens.length; i++) {
    if (!OPERATORS.has(tokens[i])) {
      const opIdx = i > 0 && OPERATORS.has(tokens[i - 1]) ? i - 1 : null;
      clauseEntries.push({ clauseIdx: i, opIdx });
    }
  }

  if (removeIndex < 0 || removeIndex >= clauseEntries.length) return query;

  const toRemove = new Set<number>();
  const { clauseIdx, opIdx } = clauseEntries[removeIndex];
  toRemove.add(clauseIdx);
  if (opIdx !== null) toRemove.add(opIdx);

  const kept = tokens.filter((_, i) => !toRemove.has(i));
  return kept.join(' ').replace(/\s+/g, ' ').trim();
}

const FIELD_COLORS: Record<string, { bg: string; border: string; color: string }> = {
  tech:           { bg: 'rgba(255,255,255,0.08)', border: 'rgba(255,255,255,0.22)', color: '#f5f5f5' },
  hostname:       { bg: 'rgba(255,255,255,0.06)', border: 'rgba(255,255,255,0.16)', color: '#d4d4d4' },
  status:         { bg: 'rgba(255,255,255,0.05)', border: 'rgba(255,255,255,0.13)', color: '#a3a3a3' },
  title:          { bg: 'rgba(255,255,255,0.06)', border: 'rgba(255,255,255,0.16)', color: '#d4d4d4' },
  vuln:           { bg: 'rgba(255,255,255,0.09)', border: 'rgba(255,255,255,0.28)', color: '#ffffff' },
  severity:       { bg: 'rgba(255,255,255,0.09)', border: 'rgba(255,255,255,0.28)', color: '#ffffff' },
  url:            { bg: 'rgba(255,255,255,0.05)', border: 'rgba(255,255,255,0.13)', color: '#a3a3a3' },
  content:        { bg: 'rgba(255,255,255,0.03)', border: 'rgba(255,255,255,0.09)', color: 'var(--text-secondary)' },
  header:         { bg: 'rgba(255,255,255,0.03)', border: 'rgba(255,255,255,0.09)', color: 'var(--text-secondary)' },
  body:           { bg: 'rgba(255,255,255,0.03)', border: 'rgba(255,255,255,0.09)', color: 'var(--text-secondary)' },
};

const DEFAULT_CHIP_COLOR = { bg: 'rgba(255,255,255,0.04)', border: 'rgba(255,255,255,0.10)', color: 'var(--text-muted)' };

const OP_LABEL: Record<string, { text: string; color: string }> = {
  AND: { text: 'AND', color: 'var(--text-muted)' },
  OR:  { text: 'OR',  color: 'var(--text-secondary)' },
  NOT: { text: 'NOT', color: '#ffffff' },
  XOR: { text: 'XOR', color: '#a3a3a3' },
};

export default function SearchBar({ value, onChange, projectId, resultCount, loading = false }: Props) {
  const [patterns, setPatterns] = useState<VulnPattern[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchVulnPatterns().then(setPatterns).catch(() => {});
  }, []);

  // Vuln autocomplete: show when user has typed "vuln:" with an optional partial name
  const vulnMatch = value.match(/(?:^|\s)vuln:(\w*)$/);
  const vulnPartial = vulnMatch ? vulnMatch[1].toLowerCase() : null;
  const suggestions = vulnPartial !== null
    ? patterns.filter((p) => p.name.startsWith(vulnPartial))
    : [];
  const shouldShowSuggestions = showSuggestions && suggestions.length > 0;

  useEffect(() => {
    if (!shouldShowSuggestions) return;
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [shouldShowSuggestions]);

  const applySuggestion = (name: string) => {
    const newValue = value.replace(/vuln:\w*$/, `vuln:${name}`);
    onChange(newValue);
    setShowSuggestions(false);
    inputRef.current?.focus();
  };

  const chips = useMemo(() => parseChips(value), [value]);
  const hasChips = chips.length > 0;

  const handleRemoveChip = (idx: number) => {
    onChange(removeChip(value, idx));
    inputRef.current?.focus();
  };

  const handleClearAll = () => {
    onChange('');
    inputRef.current?.focus();
  };

  return (
    <div ref={containerRef} style={{ display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', gap: 8,
          background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)', padding: '8px 12px',
          transition: 'border-color var(--transition-fast)',
        }}>
          {loading
            ? <Loader2 size={14} color="var(--accent-primary)" style={{ flexShrink: 0, animation: 'spin 1s linear infinite' }} />
            : <Search size={14} color="var(--text-muted)" style={{ flexShrink: 0 }} />
          }
          <input
            ref={inputRef}
            value={value}
            onChange={(e) => { onChange(e.target.value); setShowSuggestions(true); }}
            onFocus={() => setShowSuggestions(true)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setShowSuggestions(false);
              if (e.key === 'Backspace' && value === '' && hasChips) {
                handleRemoveChip(chips.length - 1);
              }
            }}
            placeholder='hostname:/^api\./ AND tech:nginx AND vuln:cors'
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              color: 'var(--text-primary)', fontSize: 12, fontFamily: 'var(--font-mono)',
            }}
          />
          {resultCount !== undefined && (
            <span style={{
              fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 600,
              color: loading ? 'var(--text-muted)' : 'var(--accent-primary)',
              background: loading ? 'transparent' : 'var(--accent-subtle)',
              border: loading ? 'none' : '1px solid var(--accent-border)',
              borderRadius: 'var(--radius-sm)', padding: '1px 7px',
              flexShrink: 0, transition: 'all var(--transition-fast)',
              minWidth: 32, textAlign: 'center',
            }}>
              {loading ? '…' : resultCount}
            </span>
          )}
          <SearchHelpButton sections={ASSET_SEARCH_SECTIONS} examples={ASSET_SEARCH_EXAMPLES} />
        </div>
        <ExportButton query={value} projectId={projectId} />
      </div>

      {hasChips && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center', paddingLeft: 2 }}>
          {chips.map((chip, idx) => {
            const color = FIELD_COLORS[chip.field] ?? DEFAULT_CHIP_COLOR;
            const opLabel = idx > 0 ? OP_LABEL[chip.op] : null;
            return (
              <React.Fragment key={idx}>
                {opLabel && (
                  <span style={{
                    fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700,
                    color: opLabel.color, letterSpacing: '0.06em', userSelect: 'none',
                  }}>
                    {opLabel.text}
                  </span>
                )}
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  background: color.bg, border: `1px solid ${color.border}`,
                  borderRadius: 'var(--radius-sm)', padding: '2px 6px 2px 8px',
                  fontSize: 11, fontFamily: 'var(--font-mono)',
                  color: color.color, maxWidth: 240,
                  transition: 'opacity var(--transition-fast)',
                }}>
                  <span style={{ fontWeight: 700, flexShrink: 0 }}>{chip.field}:</span>
                  <span style={{
                    color: 'var(--text-secondary)', overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160,
                  }}>
                    {chip.value}
                  </span>
                  <button
                    onClick={() => handleRemoveChip(idx)}
                    title={`Remove ${chip.field}: filter`}
                    style={{
                      background: 'transparent', border: 'none', cursor: 'pointer',
                      padding: 0, display: 'flex', alignItems: 'center',
                      color: 'var(--text-muted)', flexShrink: 0,
                      transition: 'color var(--transition-fast)',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.color = color.color; }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
                  >
                    <X size={10} />
                  </button>
                </span>
              </React.Fragment>
            );
          })}

          {chips.length > 1 && (
            <button
              onClick={handleClearAll}
              style={{
                background: 'transparent', border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
                padding: '2px 7px', fontSize: 10, cursor: 'pointer',
                fontFamily: 'var(--font-mono)', letterSpacing: '0.04em',
                transition: 'all var(--transition-fast)',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--status-error)'; e.currentTarget.style.borderColor = 'var(--status-error-border)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-subtle)'; }}
            >
              clear all
            </button>
          )}
        </div>
      )}

      {shouldShowSuggestions && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 200,
          background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-elevated)',
          minWidth: 260, overflow: 'hidden',
        }}>
          <div style={{
            padding: '6px 10px 4px',
            fontSize: 10, fontWeight: 700, color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.08em',
            borderBottom: '1px solid var(--border-subtle)',
          }}>
            Vulnerability Patterns
          </div>
          {suggestions.map((p) => (
            <button
              key={p.id}
              onMouseDown={(e) => { e.preventDefault(); applySuggestion(p.name); }}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                background: 'transparent', border: 'none', cursor: 'pointer',
                padding: '7px 12px',
                transition: 'background var(--transition-fast)',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-surface)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--accent-primary)' }}>
                vuln:{p.name}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                {p.description}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
