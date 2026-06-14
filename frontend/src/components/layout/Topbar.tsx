// frontend/src/components/layout/Topbar.tsx
import React from 'react';
import { useLocation } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import GlobalSearch from './GlobalSearch';

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/projects': 'Projects',
  '/data': 'Data',
  '/settings': 'Settings',
};

export default function Topbar() {
  const location = useLocation();
  const { logout, role } = useAuth();

  const path = location.pathname;
  const title = pageTitles[path] ||
    (path.startsWith('/projects/') ? 'Project View' : path.slice(1));

  return (
    <header style={{
      height: 52,
      background: 'var(--glass-bg)',
      backdropFilter: 'var(--glass-blur)',
      WebkitBackdropFilter: 'var(--glass-blur)',
      borderBottom: '1px solid var(--glass-border)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 24px',
      position: 'relative', zIndex: 100,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: '#484848', fontSize: 13, fontWeight: 400 }}>Nous</span>
        <span style={{ color: '#2e2e2e', fontSize: 12 }}>/</span>
        <span style={{ color: '#e8e8e8', fontSize: 13, fontWeight: 500 }}>{title}</span>
      </div>
      <GlobalSearch />
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{
          fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 500,
          color: '#5c5c5c',
          background: 'rgba(36, 36, 36, 0.5)',
          padding: '3px 8px', borderRadius: 4,
          border: '1px solid var(--border-subtle)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}>
          {role}
        </span>
        <button
          onClick={logout}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: '#5c5c5c', display: 'flex', padding: 6, borderRadius: 6,
            transition: 'color var(--transition-fast)',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = '#969696'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = '#5c5c5c'; }}
          title="Logout"
        >
          <LogOut size={15} />
        </button>
      </div>
    </header>
  );
}
