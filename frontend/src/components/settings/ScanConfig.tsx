// frontend/src/components/settings/ScanConfig.tsx
import React, { useEffect, useState } from 'react';
import { fetchScanConfig, updateScanConfig } from '../../api/settings';
import { useAuth } from '../../hooks/useAuth';
import { Save } from 'lucide-react';

export default function ScanConfig() {
  const [config, setConfig] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const { isAdmin } = useAuth();

  useEffect(() => {
    fetchScanConfig()
      .then((c) => {
        const stringified: Record<string, string> = {};
        for (const [k, v] of Object.entries(c)) stringified[k] = String(v ?? '');
        setConfig(stringified);
      })
      .catch(() => {});
  }, []);

  const bruteforceEnabled = config['dns_bruteforce_enabled'] !== 'false';
  const screenshotsEnabled = config['tech_screenshots_enabled'] === 'true';

  const handleChange = (key: string, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
    setMsg('');
  };

  const handleSave = async () => {
    setSaving(true);
    setMsg('');
    try {
      const payload: Record<string, unknown> = {};
      for (const { key, numeric } of fields) {
        const val = config[key];
        if (val !== undefined && val !== '') {
          payload[key] = numeric ? Number(val) : val;
        }
      }
      payload.dns_bruteforce_enabled = bruteforceEnabled;
      payload.tech_screenshots_enabled = screenshotsEnabled;
      await updateScanConfig(payload);
      setDirty(false);
      setMsg('Saved');
      setTimeout(() => setMsg(''), 2500);
    } catch {
      setMsg('Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6,
  };

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-base)', border: '1px solid var(--border-default)',
    borderRadius: 6, color: 'var(--text-primary)', padding: '10px 14px', fontSize: 14,
    width: '100%', outline: 'none', fontFamily: 'var(--font-mono)',
    transition: 'border-color var(--transition-fast), box-shadow var(--transition-fast)',
  };

  const fields = [
    { key: 'recon_timeout', label: 'Recon Timeout (seconds)', numeric: true, hint: '0 = no timeout' },
    { key: 'tech_timeout', label: 'Tech Analysis Timeout (seconds)', numeric: true, hint: '0 = no timeout' },
    { key: 'crawl_timeout', label: 'Crawl Timeout (seconds)', numeric: true, hint: '0 = no timeout' },
    { key: 'crawl_max_pages', label: 'Crawl Max Pages', numeric: true, hint: '' },
    { key: 'wordlist_path', label: 'Wordlist Path', numeric: false, hint: '' },
    { key: 'resolvers_path', label: 'Resolvers Path', numeric: false, hint: '' },
    { key: 'tech_rate_limit_delay', label: 'Tech Rate Limit Delay (seconds)', numeric: true, hint: '0 = no delay between requests' },
    { key: 'dns_rate_limit_delay', label: 'DNS Rate Limit Delay (seconds)', numeric: true, hint: '0 = no delay; > 0 forces serial DNS resolution' },
    { key: 'crawl_rate_limit_delay', label: 'Crawl Rate Limit Delay (seconds)', numeric: true, hint: '0 = no delay; > 0 forces serial page crawling' },
  ];

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, padding: 24,
      boxShadow: 'var(--shadow-card), inset 0 1px 0 rgba(255,255,255,0.02)',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 22,
      }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>Scan Configuration</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {msg && (
            <span style={{
              fontSize: 12, fontFamily: 'var(--font-mono)',
              color: msg === 'Saved' ? 'var(--status-success)' : 'var(--status-error)',
            }}>{msg}</span>
          )}
          {isAdmin && (
            <button onClick={handleSave} disabled={!dirty || saving} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: dirty ? 'var(--accent-primary)' : 'var(--bg-elevated)',
              color: dirty ? 'var(--bg-base)' : 'var(--text-muted)',
              border: dirty ? '1px solid var(--accent-dim)' : '1px solid var(--border-default)',
              borderRadius: 6, padding: '7px 16px', fontSize: 13, fontWeight: 600, cursor: dirty ? 'pointer' : 'default',
              opacity: saving ? 0.6 : 1,
              transition: 'all var(--transition-fast)',
            }}>
              <Save size={13} />
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          )}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {fields.map(({ key, label, hint }) => (
          <div key={key}>
            <div style={labelStyle}>{label}</div>
            <input
              value={config[key] ?? ''}
              onChange={(e) => handleChange(key, e.target.value)}
              readOnly={!isAdmin}
              style={{
                ...inputStyle,
                cursor: isAdmin ? 'text' : 'default',
                opacity: isAdmin ? 1 : 0.7,
              }}
            />
            {hint && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
                {hint}
              </div>
            )}
          </div>
        ))}
      </div>
      <div style={{
        marginTop: 20, paddingTop: 20, borderTop: '1px solid var(--border-subtle)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>DNS Bruteforce</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>
            Enumerate subdomains via wordlist bruteforce during recon
          </div>
        </div>
        <div
          onClick={() => { if (isAdmin) handleChange('dns_bruteforce_enabled', bruteforceEnabled ? 'false' : 'true'); }}
          style={{
            width: 40, height: 22, borderRadius: 11, flexShrink: 0,
            background: bruteforceEnabled ? 'var(--accent-primary)' : 'var(--bg-elevated)',
            border: '1px solid var(--border-default)',
            position: 'relative', cursor: isAdmin ? 'pointer' : 'default',
            opacity: isAdmin ? 1 : 0.7,
            transition: 'background var(--transition-fast)',
          }}
        >
          <div style={{
            position: 'absolute', top: 2,
            left: bruteforceEnabled ? 20 : 2,
            width: 16, height: 16, borderRadius: '50%',
            background: bruteforceEnabled ? 'var(--bg-base)' : '#fff',
            transition: 'left var(--transition-fast), background var(--transition-fast)',
          }} />
        </div>
      </div>
      <div style={{
        marginTop: 18, paddingTop: 18, borderTop: '1px solid var(--border-subtle)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>Take Screenshots</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>
            Capture a screenshot of each asset after page load during tech analysis
          </div>
        </div>
        <div
          onClick={() => { if (isAdmin) handleChange('tech_screenshots_enabled', screenshotsEnabled ? 'false' : 'true'); }}
          style={{
            width: 40, height: 22, borderRadius: 11, flexShrink: 0,
            background: screenshotsEnabled ? 'var(--accent-primary)' : 'var(--bg-elevated)',
            border: '1px solid var(--border-default)',
            position: 'relative', cursor: isAdmin ? 'pointer' : 'default',
            opacity: isAdmin ? 1 : 0.7,
            transition: 'background var(--transition-fast)',
          }}
        >
          <div style={{
            position: 'absolute', top: 2,
            left: screenshotsEnabled ? 20 : 2,
            width: 16, height: 16, borderRadius: '50%',
            background: screenshotsEnabled ? 'var(--bg-base)' : '#fff',
            transition: 'left var(--transition-fast), background var(--transition-fast)',
          }} />
        </div>
      </div>
    </div>
  );
}
