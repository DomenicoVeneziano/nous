// frontend/src/components/shared/SearchHelpButton.tsx
import React, { useState, useEffect, useRef } from 'react';
import { HelpCircle } from 'lucide-react';

interface Section {
  heading: string;
  rows: { label: string; desc: string }[];
}

interface Example {
  query: string;
  desc: string;
}

interface Props {
  sections: Section[];
  examples?: Example[];
}

export default function SearchHelpButton({ sections, examples }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  return (
    <div ref={ref} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
      <button
        onClick={() => setOpen(v => !v)}
        title="Search syntax help"
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'none', border: 'none', padding: 2, cursor: 'pointer',
          color: open ? 'var(--accent-primary)' : 'var(--text-muted)',
          transition: 'color var(--transition-fast)',
          flexShrink: 0,
        }}
        onMouseEnter={e => { if (!open) (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-secondary)'; }}
        onMouseLeave={e => { if (!open) (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-muted)'; }}
      >
        <HelpCircle size={13} />
      </button>

      {open && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 10px)',
          right: 0,
          zIndex: 1000,
          width: 380,
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-elevated)',
          padding: '16px 18px',
          animation: 'fadeIn 120ms ease',
        }}>
          {/* Arrow */}
          <div style={{
            position: 'absolute', top: -5, right: 10,
            width: 8, height: 8,
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-default)',
            borderBottom: 'none', borderRight: 'none',
            transform: 'rotate(45deg)',
          }} />

          {sections.map((section, si) => (
            <div key={si} style={{ marginBottom: si < sections.length - 1 ? 14 : 0 }}>
              <div style={{
                fontSize: 10, fontWeight: 700, color: 'var(--text-muted)',
                textTransform: 'uppercase', letterSpacing: '0.08em',
                marginBottom: 8,
              }}>
                {section.heading}
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <tbody>
                  {section.rows.map((row, ri) => (
                    <tr key={ri}>
                      <td style={{
                        paddingBottom: ri < section.rows.length - 1 ? 5 : 0,
                        paddingRight: 14,
                        verticalAlign: 'top',
                        width: '40%',
                      }}>
                        <code style={{
                          fontSize: 11, color: 'var(--accent-primary)',
                          fontFamily: 'var(--font-mono)', background: 'var(--accent-subtle)',
                          padding: '1px 5px', borderRadius: 3,
                          whiteSpace: 'nowrap',
                        }}>
                          {row.label}
                        </code>
                      </td>
                      <td style={{
                        fontSize: 11, color: 'var(--text-secondary)',
                        paddingBottom: ri < section.rows.length - 1 ? 5 : 0,
                        verticalAlign: 'top',
                      }}>
                        {row.desc}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}

          {examples && examples.length > 0 && (
            <>
              <div style={{
                height: 1, background: 'var(--border-subtle)',
                margin: '14px 0 12px',
              }} />
              <div style={{
                fontSize: 10, fontWeight: 700, color: 'var(--text-muted)',
                textTransform: 'uppercase', letterSpacing: '0.08em',
                marginBottom: 8,
              }}>
                Examples
              </div>
              {examples.map((ex, ei) => (
                <div key={ei} style={{ marginBottom: ei < examples.length - 1 ? 7 : 0 }}>
                  <code style={{
                    display: 'block', fontSize: 11, color: 'var(--text-code)',
                    fontFamily: 'var(--font-mono)', marginBottom: 2,
                  }}>
                    {ex.query}
                  </code>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', paddingLeft: 2 }}>
                    {ex.desc}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
