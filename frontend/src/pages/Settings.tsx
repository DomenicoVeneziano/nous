// frontend/src/pages/Settings.tsx
import React, { useState } from 'react';
import ScanConfig from '../components/settings/ScanConfig';
import ProxyConfig from '../components/settings/ProxyConfig';
import UserManagement from '../components/settings/UserManagement';
import ApiKeyManagement from '../components/settings/ApiKeyManagement';
import VulnPatternManagement from '../components/settings/VulnPatternManagement';
import { useAuth } from '../hooks/useAuth';

type Tab = 'config' | 'proxy' | 'users' | 'api-keys' | 'vuln-patterns';

export default function Settings() {
  const { isAdmin } = useAuth();
  const [tab, setTab] = useState<Tab>('config');

  const tabs: { key: Tab; label: string }[] = [
    { key: 'config', label: 'Scan Config' },
    { key: 'proxy', label: 'Proxy' },
    { key: 'api-keys', label: 'API Keys' },
    { key: 'vuln-patterns', label: 'Vuln Patterns' },
    ...(isAdmin ? [{ key: 'users' as Tab, label: 'Users' }] : []),
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div>
        <h2 style={{ color: 'var(--text-primary)', fontSize: 20, fontWeight: 700, margin: '0 0 16px' }}>Settings</h2>
        <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border-subtle)' }}>
          {tabs.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              style={{
                background: 'transparent', border: 'none',
                borderBottom: tab === key ? '2px solid var(--accent-primary)' : '2px solid transparent',
                color: tab === key ? 'var(--accent-primary)' : 'var(--text-muted)',
                padding: '8px 18px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                marginBottom: -1, transition: 'all var(--transition-fast)',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {tab === 'config' && <ScanConfig />}
      {tab === 'proxy' && <ProxyConfig />}
      {tab === 'api-keys' && <ApiKeyManagement />}
      {tab === 'vuln-patterns' && <VulnPatternManagement />}
      {tab === 'users' && isAdmin && <UserManagement />}
    </div>
  );
}
