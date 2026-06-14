// frontend/src/components/layout/Navbar.tsx
import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Shield, LogOut } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import GlobalSearch from './GlobalSearch';

const navItems = [
  { path: '/', label: 'Dashboard' },
  { path: '/projects', label: 'Projects' },
  { path: '/data', label: 'Data' },
  { path: '/settings', label: 'Settings' },
];

export default function Navbar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout, role } = useAuth();

  return (
    <header style={{
      height: 52, minHeight: 52,
      background: 'var(--glass-bg)',
      backdropFilter: 'var(--glass-blur)',
      WebkitBackdropFilter: 'var(--glass-blur)',
      borderBottom: '1px solid var(--glass-border)',
      display: 'flex', alignItems: 'center',
      padding: '0 24px', gap: 32,
      position: 'sticky', top: 0, zIndex: 200,
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <div style={{ filter: 'drop-shadow(0 0 8px rgba(255,255,255,0.15))', display: 'flex', alignItems: 'center' }}>
          <Shield size={20} color="var(--accent-primary)" />
        </div>
        <span style={{
          fontSize: 15, fontWeight: 700, letterSpacing: '0.02em',
          color: 'var(--text-primary)',
        }}>
          Nous
        </span>
      </div>

      {/* Nav links */}
      <nav style={{ display: 'flex', alignItems: 'stretch', height: 52, gap: 0 }}>
        {navItems.map(({ path, label }) => {
          const active = path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              style={{
                background: 'transparent',
                border: 'none',
                borderBottom: active ? '2px solid var(--accent-primary)' : '2px solid transparent',
                borderTop: '2px solid transparent',
                padding: '0 14px',
                cursor: 'pointer',
                color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                fontSize: 13,
                fontWeight: active ? 500 : 400,
                fontFamily: 'var(--font-sans)',
                transition: 'color var(--transition-fast), border-color var(--transition-fast)',
                display: 'flex', alignItems: 'center',
              }}
              onMouseEnter={(e) => {
                if (!active) e.currentTarget.style.color = 'var(--text-secondary)';
              }}
              onMouseLeave={(e) => {
                if (!active) e.currentTarget.style.color = 'var(--text-muted)';
              }}
            >
              {label}
            </button>
          );
        })}
      </nav>

      {/* Right region */}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
        <GlobalSearch />
        <span style={{
          fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 600,
          color: 'var(--text-muted)',
          background: 'var(--bg-elevated)',
          padding: '3px 8px', borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border-subtle)',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        }}>
          {role}
        </span>
        <button
          onClick={logout}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: 'var(--text-muted)', display: 'flex', padding: 6,
            borderRadius: 'var(--radius-md)',
            transition: 'color var(--transition-fast), background var(--transition-fast)',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = 'var(--text-secondary)';
            e.currentTarget.style.background = 'var(--bg-hover)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = 'var(--text-muted)';
            e.currentTarget.style.background = 'transparent';
          }}
          title="Logout"
        >
          <LogOut size={15} />
        </button>
      </div>
    </header>
  );
}
