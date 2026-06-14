// frontend/src/components/shared/markdownComponents.tsx
import React from 'react';
import type ReactMarkdown from 'react-markdown';

export const mdComponents: React.ComponentProps<typeof ReactMarkdown>['components'] = {
  p:          ({ children }) => <p style={{ margin: '0 0 8px', color: 'var(--text-primary)', fontSize: 12, lineHeight: 1.65 }}>{children}</p>,
  h1:         ({ children }) => <h1 style={{ color: 'var(--text-primary)', fontSize: 14, fontWeight: 700, margin: '12px 0 6px', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>{children}</h1>,
  h2:         ({ children }) => <h2 style={{ color: 'var(--text-primary)', fontSize: 13, fontWeight: 700, margin: '10px 0 5px' }}>{children}</h2>,
  h3:         ({ children }) => <h3 style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 600, margin: '8px 0 4px' }}>{children}</h3>,
  ul:         ({ children }) => <ul style={{ margin: '0 0 8px', paddingLeft: 18, color: 'var(--text-primary)', fontSize: 12 }}>{children}</ul>,
  ol:         ({ children }) => <ol style={{ margin: '0 0 8px', paddingLeft: 18, color: 'var(--text-primary)', fontSize: 12 }}>{children}</ol>,
  li:         ({ children }) => <li style={{ marginBottom: 3, lineHeight: 1.5 }}>{children}</li>,
  code:       ({ children, className }) => {
    const isBlock = className?.includes('language-');
    return isBlock ? (
      <code style={{ display: 'block', background: 'var(--bg-void)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', padding: '8px 12px', fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-code)', overflowX: 'auto', lineHeight: 1.6 }}>{children}</code>
    ) : (
      <code style={{ background: 'var(--bg-void)', borderRadius: 3, padding: '1px 5px', fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-code)' }}>{children}</code>
    );
  },
  pre:        ({ children }) => <pre style={{ margin: '0 0 8px', background: 'transparent' }}>{children}</pre>,
  blockquote: ({ children }) => <blockquote style={{ borderLeft: '3px solid var(--accent-primary)', margin: '8px 0', paddingLeft: 12, color: 'var(--text-secondary)', fontStyle: 'italic', fontSize: 12 }}>{children}</blockquote>,
  a:          ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-primary)', textDecoration: 'underline', fontSize: 12 }}>{children}</a>,
  strong:     ({ children }) => <strong style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{children}</strong>,
  em:         ({ children }) => <em style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>{children}</em>,
  hr:         () => <hr style={{ border: 'none', borderTop: '1px solid var(--border-subtle)', margin: '10px 0' }} />,
};
