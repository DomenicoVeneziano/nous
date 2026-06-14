// frontend/src/components/settings/ProxyConfig.tsx
import React, { useEffect, useState } from 'react';
import { fetchProxyConfig, updateProxyConfig, testProxyConfig, type ProxyConfig as ProxyConfigData } from '../../api/settings';
import { useAuth } from '../../hooks/useAuth';
import { Save, Plug } from 'lucide-react';

const EMPTY: ProxyConfigData = {
  enabled: false, scheme: 'http', host: '', port: 8080,
  username: '', password_set: false, recon: false, tech: false, crawl: false,
};

const SCAN_TYPES: { key: 'recon' | 'tech' | 'crawl'; label: string; hint: string }[] = [
  { key: 'recon', label: 'Recon', hint: 'Subdomain enumeration HTTP sources (subfinder, gau, waymore, crt.sh)' },
  { key: 'tech', label: 'Tech Analysis', hint: 'Browser-based technology fingerprinting' },
  { key: 'crawl', label: 'Crawl', hint: 'Browser-based endpoint crawling' },
];

export default function ProxyConfig() {
  const [cfg, setCfg] = useState<ProxyConfigData>(EMPTY);
  const [password, setPassword] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState('');
  const [msgErr, setMsgErr] = useState(false);
  const { isAdmin } = useAuth();

  useEffect(() => {
    fetchProxyConfig().then(setCfg).catch(() => {});
  }, []);

  const set = <K extends keyof ProxyConfigData>(key: K, value: ProxyConfigData[K]) => {
    setCfg((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
    setMsg('');
  };

  const flash = (text: string, isErr = false) => {
    setMsg(text);
    setMsgErr(isErr);
    setTimeout(() => setMsg(''), 3500);
  };

  const handleSave = async () => {
    setSaving(true);
    setMsg('');
    try {
      const payload: Parameters<typeof updateProxyConfig>[0] = {
        enabled: cfg.enabled, scheme: cfg.scheme, host: cfg.host.trim(), port: Number(cfg.port),
        username: cfg.username, recon: cfg.recon, tech: cfg.tech, crawl: cfg.crawl,
      };
      if (password) payload.password = password;
      const saved = await updateProxyConfig(payload);
      setCfg(saved);
      setPassword('');
      setDirty(false);
      flash('Saved');
    } catch (e: any) {
      flash(e?.response?.data?.detail || 'Failed to save', true);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!cfg.host.trim()) { flash('Enter a host to test', true); return; }
    setTesting(true);
    setMsg('');
    try {
      const res = await testProxyConfig(cfg.host.trim(), Number(cfg.port));
      flash(res.message, !res.reachable);
    } catch (e: any) {
      flash(e?.response?.data?.detail || 'Test failed', true);
    } finally {
      setTesting(false);
    }
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6,
  };
  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-base)', border: '1px solid var(--border-default)',
    borderRadius: 6, color: 'var(--text-primary)', padding: '10px 14px', fontSize: 14,
    width: '100%', outline: 'none', fontFamily: 'var(--font-mono)', boxSizing: 'border-box',
    transition: 'border-color var(--transition-fast), box-shadow var(--transition-fast)',
  };
  const disabledInput = (extra: React.CSSProperties = {}): React.CSSProperties => ({
    ...inputStyle, cursor: isAdmin ? 'text' : 'default', opacity: isAdmin ? 1 : 0.7, ...extra,
  });

  const Toggle = ({ on, onClick }: { on: boolean; onClick: () => void }) => (
    <div
      onClick={() => { if (isAdmin) onClick(); }}
      style={{
        width: 40, height: 22, borderRadius: 11, flexShrink: 0,
        background: on ? 'var(--accent-primary)' : 'var(--bg-elevated)',
        border: '1px solid var(--border-default)', position: 'relative',
        cursor: isAdmin ? 'pointer' : 'default', opacity: isAdmin ? 1 : 0.7,
        transition: 'background var(--transition-fast)',
      }}
    >
      <div style={{
        position: 'absolute', top: 2, left: on ? 20 : 2, width: 16, height: 16, borderRadius: '50%',
        background: on ? 'var(--bg-base)' : '#fff',
        transition: 'left var(--transition-fast), background var(--transition-fast)',
      }} />
    </div>
  );

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, padding: 24,
      boxShadow: 'var(--shadow-card), inset 0 1px 0 rgba(255,255,255,0.02)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 22 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>Proxy</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {msg && (
            <span style={{
              fontSize: 12, fontFamily: 'var(--font-mono)',
              color: msgErr ? 'var(--status-error)' : 'var(--status-success)',
            }}>{msg}</span>
          )}
          {isAdmin && (
            <>
              <button onClick={handleTest} disabled={testing || saving} style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
                border: '1px solid var(--border-default)', borderRadius: 6,
                padding: '7px 14px', fontSize: 13, fontWeight: 600,
                cursor: testing ? 'default' : 'pointer', opacity: testing ? 0.6 : 1,
                transition: 'all var(--transition-fast)',
              }}>
                <Plug size={13} />
                {testing ? 'Testing...' : 'Test'}
              </button>
              <button onClick={handleSave} disabled={!dirty || saving} style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: dirty ? 'var(--accent-primary)' : 'var(--bg-elevated)',
                color: dirty ? 'var(--bg-base)' : 'var(--text-muted)',
                border: dirty ? '1px solid var(--accent-dim)' : '1px solid var(--border-default)',
                borderRadius: 6, padding: '7px 16px', fontSize: 13, fontWeight: 600,
                cursor: dirty ? 'pointer' : 'default', opacity: saving ? 0.6 : 1,
                transition: 'all var(--transition-fast)',
              }}>
                <Save size={13} />
                {saving ? 'Saving...' : 'Save Changes'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Enable toggle */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 22 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>Enable Proxy</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>
            Master switch — when off, all scans connect directly
          </div>
        </div>
        <Toggle on={cfg.enabled} onClick={() => set('enabled', !cfg.enabled)} />
      </div>

      {/* Connection fields */}
      <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 140px', gap: 16, marginBottom: 20 }}>
        <div>
          <div style={labelStyle}>Scheme</div>
          <select
            value={cfg.scheme}
            onChange={(e) => set('scheme', e.target.value)}
            disabled={!isAdmin}
            style={disabledInput()}
          >
            <option value="http">http</option>
            <option value="https">https</option>
            <option value="socks5">socks5</option>
          </select>
        </div>
        <div>
          <div style={labelStyle}>Host</div>
          <input
            value={cfg.host}
            onChange={(e) => set('host', e.target.value)}
            placeholder="127.0.0.1"
            readOnly={!isAdmin}
            style={disabledInput()}
          />
        </div>
        <div>
          <div style={labelStyle}>Port</div>
          <input
            type="number"
            value={cfg.port}
            onChange={(e) => set('port', Number(e.target.value))}
            readOnly={!isAdmin}
            style={disabledInput()}
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 4 }}>
        <div>
          <div style={labelStyle}>Username <span style={{ color: 'var(--text-muted)' }}>(optional)</span></div>
          <input
            value={cfg.username}
            onChange={(e) => set('username', e.target.value)}
            autoComplete="off"
            readOnly={!isAdmin}
            style={disabledInput()}
          />
        </div>
        <div>
          <div style={labelStyle}>Password <span style={{ color: 'var(--text-muted)' }}>(optional)</span></div>
          <input
            type="password"
            value={password}
            onChange={(e) => { setPassword(e.target.value); setDirty(true); setMsg(''); }}
            placeholder={cfg.password_set ? '•••••••• (unchanged)' : ''}
            autoComplete="new-password"
            readOnly={!isAdmin}
            style={disabledInput()}
          />
        </div>
      </div>

      {/* Per-scan-type selection */}
      <div style={{ marginTop: 20, paddingTop: 20, borderTop: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
          Apply Proxy To
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 14, fontFamily: 'var(--font-mono)' }}>
          Only selected scan types route through the proxy; the rest connect directly
        </div>
        {SCAN_TYPES.map(({ key, label, hint }) => (
          <div key={key} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 0', borderTop: '1px solid var(--border-subtle)',
          }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>{label}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>{hint}</div>
            </div>
            <Toggle on={cfg[key]} onClick={() => set(key, !cfg[key])} />
          </div>
        ))}
      </div>
    </div>
  );
}
