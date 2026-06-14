// frontend/src/components/layout/PageShell.tsx
import React from 'react';
import Navbar from './Navbar';

interface Props {
  children: React.ReactNode;
}

export default function PageShell({ children }: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-base)' }}>
      <Navbar />
      <main style={{
        flex: 1, overflow: 'auto', padding: '28px 32px',
        background: 'var(--bg-base)',
      }}>
        <div style={{ maxWidth: 1440, margin: '0 auto', height: '100%' }}>
          {children}
        </div>
      </main>
    </div>
  );
}
