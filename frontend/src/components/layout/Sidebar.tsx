// frontend/src/components/layout/Sidebar.tsx
import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { LayoutDashboard, FolderOpen, Database, Settings, ChevronLeft, ChevronRight, Shield } from 'lucide-react';

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/projects', label: 'Projects', icon: FolderOpen },
  { path: '/data', label: 'Data', icon: Database },
  { path: '/settings', label: 'Settings', icon: Settings },
];

// Isometric pattern for active nav item
const hatchBg = [
  'linear-gradient(30deg,  rgba(232,232,232,0.38) 12%, transparent 12.5%, transparent 87%, rgba(232,232,232,0.38) 87.5%, rgba(232,232,232,0.38))',
  'linear-gradient(150deg, rgba(232,232,232,0.38) 12%, transparent 12.5%, transparent 87%, rgba(232,232,232,0.38) 87.5%, rgba(232,232,232,0.38))',
  'linear-gradient(30deg,  rgba(232,232,232,0.38) 12%, transparent 12.5%, transparent 87%, rgba(232,232,232,0.38) 87.5%, rgba(232,232,232,0.38))',
  'linear-gradient(150deg, rgba(232,232,232,0.38) 12%, transparent 12.5%, transparent 87%, rgba(232,232,232,0.38) 87.5%, rgba(232,232,232,0.38))',
  'linear-gradient(60deg,  rgba(232,232,232,0.20) 25%, transparent 25.5%, transparent 75%, rgba(232,232,232,0.20) 75%, rgba(232,232,232,0.20))',
  'linear-gradient(60deg,  rgba(232,232,232,0.20) 25%, transparent 25.5%, transparent 75%, rgba(232,232,232,0.20) 75%, rgba(232,232,232,0.20))',
].join(', ');

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const width = collapsed ? 60 : 240;

  return (
    <aside style={{
      width, minWidth: width, height: '100vh',
      background: 'var(--glass-bg)',
      backdropFilter: 'var(--glass-blur)',
      WebkitBackdropFilter: 'var(--glass-blur)',
      borderRight: '1px solid var(--glass-border)',
      display: 'flex', flexDirection: 'column',
      transition: 'width var(--transition-slow)',
    }}>
      {/* Logo */}
      <div style={{
        height: 52, display: 'flex', alignItems: 'center', gap: 10,
        padding: '0 16px', borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{
          filter: 'drop-shadow(0 0 6px rgba(200, 200, 200, 0.18))',
          display: 'flex', alignItems: 'center',
        }}>
          <Shield size={22} color="#c8c8c8" />
        </div>
        {!collapsed && (
          <span style={{
            color: '#e8e8e8', fontSize: 16, fontWeight: 600,
            letterSpacing: '0.04em',
            background: 'linear-gradient(135deg, #e8e8e8 0%, #888888 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>
            Nous
          </span>
        )}
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: '16px 8px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {navItems.map(({ path, label, icon: Icon }) => {
          const active = path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: collapsed ? '10px 0' : '10px 14px',
                justifyContent: collapsed ? 'center' : 'flex-start',
                backgroundImage: active ? hatchBg : 'none',
                backgroundSize: active ? '20px 35px' : 'auto',
                backgroundPosition: active ? '0 0, 0 0, 10px 18px, 10px 18px, 0 0, 10px 18px' : '0 0',
                backgroundColor: active ? 'rgba(200, 200, 200, 0.06)' : 'transparent',
                borderLeft: active ? '2px solid #c8c8c8' : '2px solid transparent',
                border: 'none',
                borderRadius: 6, cursor: 'pointer',
                color: active ? '#f0f0f0' : '#969696',
                fontSize: 14, fontWeight: active ? 500 : 400,
                transition: 'all var(--transition-base)',
                width: '100%',
                position: 'relative',
                overflow: 'hidden',
              }}
              onMouseEnter={(e) => {
                if (!active) {
                  e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.04)';
                  e.currentTarget.style.color = '#e8e8e8';
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  e.currentTarget.style.backgroundColor = 'transparent';
                  e.currentTarget.style.color = '#969696';
                }
              }}
            >
              {active && (
                <div style={{
                  position: 'absolute', left: 0, top: '20%', bottom: '20%', width: 2,
                  background: 'linear-gradient(180deg, transparent, #c8c8c8, transparent)',
                  borderRadius: 1,
                }} />
              )}
              <div style={{
                filter: active ? 'drop-shadow(0 0 5px rgba(200, 200, 200, 0.35))' : 'none',
                display: 'flex', alignItems: 'center',
                transition: 'filter var(--transition-base)',
              }}>
                <Icon size={17} color={active ? '#c8c8c8' : '#5c5c5c'} strokeWidth={active ? 2 : 1.5} />
              </div>
              {!collapsed && label}
            </button>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          padding: 14, display: 'flex', justifyContent: 'center',
          borderTop: '1px solid var(--border-subtle)', color: '#5c5c5c',
          transition: 'color var(--transition-fast)',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.color = '#969696'; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = '#5c5c5c'; }}
      >
        {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>
    </aside>
  );
}
