// frontend/src/components/settings/NotificationConfig.tsx
import React, { useEffect, useState } from 'react';
import {
  fetchNotificationConfig, updateNotificationConfig, testNotificationConfig,
  type NotificationConfig as NotificationConfigData,
  type NotificationConfigUpdate,
  type NotificationSecretField,
  type NotificationChannel,
} from '../../api/settings';
import { useAuth } from '../../hooks/useAuth';
import { Save, Plug, X } from 'lucide-react';

const EMPTY: NotificationConfigData = {
  enabled: false, on_success: false, on_failure: false,
  slack_enabled: false, slack_webhook_url_set: false,
  discord_enabled: false, discord_webhook_url_set: false,
  webhook_enabled: false, webhook_url_set: false, webhook_token_set: false,
  telegram_enabled: false, telegram_bot_token_set: false, telegram_chat_id: '',
  sample_size: 5, timeout_seconds: 10, retries: 2,
};

const MASKED = '•••••••• (stored, unchanged)';

const SECRET_FIELDS: NotificationSecretField[] = [
  'slack_webhook_url', 'discord_webhook_url', 'webhook_url', 'webhook_token', 'telegram_bot_token',
];

type Secrets = Record<NotificationSecretField, string>;

const EMPTY_SECRETS: Secrets = {
  slack_webhook_url: '', discord_webhook_url: '', webhook_url: '', webhook_token: '', telegram_bot_token: '',
};

// Mirrors the shapes the backend enforces, so the common typo never has to
// round-trip. Kept in step with backend/routers/settings.py.
const TELEGRAM_TOKEN_RE = /^[0-9]{1,20}:[A-Za-z0-9_-]{20,256}$/;
const TELEGRAM_CHAT_ID_RE = /^(-?[0-9]{1,32}|@[A-Za-z0-9_]{5,32})$/;

// A FastAPI error body is a plain string for a raised HTTPException, but an
// ARRAY of error objects for a 422 raised by request validation. Rendering
// either of the latter as a React child throws and blanks the whole Settings
// page, so every shape is flattened to a readable line here.
function errorText(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail;
  const parts: string[] = [];
  if (typeof detail === 'string') {
    parts.push(detail);
  } else if (Array.isArray(detail)) {
    for (const item of detail) {
      if (typeof item === 'string') { parts.push(item); continue; }
      const loc = Array.isArray(item?.loc)
        ? item.loc.filter((p: unknown) => typeof p === 'string' && p !== 'body').join('.')
        : '';
      const msg = typeof item?.msg === 'string' ? item.msg : '';
      const line = [loc, msg].filter(Boolean).join(': ');
      if (line) parts.push(line);
    }
  } else if (detail && typeof detail === 'object') {
    if (typeof (detail as any).msg === 'string') parts.push((detail as any).msg);
  }
  const text = parts.join('; ').trim() || (typeof e?.message === 'string' ? e.message : '');
  if (!text) return fallback;
  return text.length > 200 ? `${text.slice(0, 197)}...` : text;
}

const TUNING: { key: 'sample_size' | 'timeout_seconds' | 'retries'; label: string; hint: string; min: number; max: number }[] = [
  { key: 'sample_size', label: 'Sample Size', hint: 'How many new assets to list in the message body (0-20)', min: 0, max: 20 },
  { key: 'timeout_seconds', label: 'Timeout', hint: 'Seconds to wait for each delivery attempt (1-30)', min: 1, max: 30 },
  { key: 'retries', label: 'Retries', hint: 'Extra delivery attempts after the first failure (0-5)', min: 0, max: 5 },
];

export default function NotificationConfig() {
  const [cfg, setCfg] = useState<NotificationConfigData>(EMPTY);
  const [secrets, setSecrets] = useState<Secrets>(EMPTY_SECRETS);
  const [cleared, setCleared] = useState<NotificationSecretField[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<NotificationChannel | null>(null);
  const [msg, setMsg] = useState('');
  const [msgErr, setMsgErr] = useState(false);
  const { isAdmin } = useAuth();

  useEffect(() => {
    fetchNotificationConfig().then(setCfg).catch(() => {});
  }, []);

  const set = <K extends keyof NotificationConfigData>(key: K, value: NotificationConfigData[K]) => {
    setCfg((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
    setMsg('');
  };

  const setSecret = (field: NotificationSecretField, value: string) => {
    setSecrets((prev) => ({ ...prev, [field]: value }));
    setCleared((prev) => prev.filter((f) => f !== field));
    setDirty(true);
    setMsg('');
  };

  const toggleClear = (field: NotificationSecretField) => {
    setSecrets((prev) => ({ ...prev, [field]: '' }));
    setCleared((prev) => (prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field]));
    setDirty(true);
    setMsg('');
  };

  const flash = (text: string, isErr = false) => {
    setMsg(text);
    setMsgErr(isErr);
    setTimeout(() => setMsg(''), 3500);
  };

  const clamp = (value: number, min: number, max: number) => {
    if (!Number.isFinite(value)) return min;
    return Math.min(max, Math.max(min, Math.trunc(value)));
  };

  const handleSave = async () => {
    const chatId = cfg.telegram_chat_id.trim();
    const botToken = secrets.telegram_bot_token.trim();
    const botTokenStays = Boolean(botToken)
      || (cfg.telegram_bot_token_set && !cleared.includes('telegram_bot_token'));
    if (botToken && !TELEGRAM_TOKEN_RE.test(botToken)) {
      flash('Bot Token must look like 123456:AA... (digits, a colon, then the secret)', true);
      return;
    }
    if (chatId && !TELEGRAM_CHAT_ID_RE.test(chatId)) {
      flash('Chat ID must be a numeric id or an @username', true);
      return;
    }
    // The chat id is not a secret: an empty box is saved as empty, so leaving
    // Telegram on would enable a channel with nowhere to send. Say so here
    // rather than letting the request come back a 400.
    if (cfg.telegram_enabled && !chatId) {
      flash('Chat ID is required while Telegram is enabled', true);
      return;
    }
    if (cfg.telegram_enabled && !botTokenStays) {
      flash('Bot Token is required while Telegram is enabled', true);
      return;
    }
    setSaving(true);
    setMsg('');
    try {
      const payload: NotificationConfigUpdate = {
        enabled: cfg.enabled, on_success: cfg.on_success, on_failure: cfg.on_failure,
        slack_enabled: cfg.slack_enabled,
        discord_enabled: cfg.discord_enabled,
        webhook_enabled: cfg.webhook_enabled,
        telegram_enabled: cfg.telegram_enabled,
        telegram_chat_id: chatId,
        sample_size: clamp(Number(cfg.sample_size), 0, 20),
        timeout_seconds: clamp(Number(cfg.timeout_seconds), 1, 30),
        retries: clamp(Number(cfg.retries), 0, 5),
      };
      for (const field of SECRET_FIELDS) {
        const value = secrets[field].trim();
        if (value) payload[field] = value;
      }
      if (cleared.length) payload.clear_secrets = cleared;
      const saved = await updateNotificationConfig(payload);
      setCfg(saved);
      setSecrets(EMPTY_SECRETS);
      setCleared([]);
      setDirty(false);
      flash('Saved');
    } catch (e: any) {
      flash(errorText(e, 'Failed to save'), true);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async (channel: NotificationChannel) => {
    setTesting(channel);
    setMsg('');
    try {
      const res = await testNotificationConfig(channel);
      flash(res.message, !res.ok);
    } catch (e: any) {
      flash(errorText(e, 'Test failed'), true);
    } finally {
      setTesting(null);
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

  const secretField = ({ field, label, isSet, placeholder }: {
    field: NotificationSecretField; label: string; isSet: boolean; placeholder: string;
  }) => {
    const pendingClear = cleared.includes(field);
    return (
      <div>
        <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>{label}</span>
          {isSet && isAdmin && (
            <button
              onClick={() => toggleClear(field)}
              style={{
                display: 'flex', alignItems: 'center', gap: 4,
                background: 'transparent', border: 'none', padding: 0,
                color: pendingClear ? 'var(--status-error)' : 'var(--text-muted)',
                fontSize: 11, fontWeight: 600, fontFamily: 'var(--font-mono)', cursor: 'pointer',
              }}
            >
              <X size={11} />
              {pendingClear ? 'Will be cleared — undo' : 'Clear'}
            </button>
          )}
        </div>
        <input
          type="password"
          value={secrets[field]}
          onChange={(e) => setSecret(field, e.target.value)}
          placeholder={pendingClear ? 'Cleared on save' : (isSet ? MASKED : placeholder)}
          autoComplete="new-password"
          readOnly={!isAdmin}
          style={disabledInput(pendingClear ? { borderColor: 'var(--status-error)' } : {})}
        />
      </div>
    );
  };

  const testButton = (channel: NotificationChannel) => (
    <button onClick={() => handleTest(channel)} disabled={testing !== null || saving} style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
      border: '1px solid var(--border-default)', borderRadius: 6,
      padding: '7px 14px', fontSize: 13, fontWeight: 600,
      cursor: testing !== null ? 'default' : 'pointer', opacity: testing !== null ? 0.6 : 1,
      transition: 'all var(--transition-fast)',
    }}>
      <Plug size={13} />
      {testing === channel ? 'Testing...' : 'Test'}
    </button>
  );

  const channelHeader = ({ title, hint, on, onToggle, channel }: {
    title: string; hint: string; on: boolean; onToggle: () => void; channel: NotificationChannel;
  }) => (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{title}</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>{hint}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {isAdmin && testButton(channel)}
        <Toggle on={on} onClick={onToggle} />
      </div>
    </div>
  );

  const sectionStyle: React.CSSProperties = {
    marginTop: 20, paddingTop: 20, borderTop: '1px solid var(--border-subtle)',
  };

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, padding: 24,
      boxShadow: 'var(--shadow-card), inset 0 1px 0 rgba(255,255,255,0.02)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 22 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>Notifications</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {msg && (
            <span style={{
              fontSize: 12, fontFamily: 'var(--font-mono)',
              color: msgErr ? 'var(--status-error)' : 'var(--status-success)',
            }}>{msg}</span>
          )}
          {isAdmin && (
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
          )}
        </div>
      </div>

      {/* Master switch */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>Enable Notifications</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>
            Master switch — when off, no channel is notified
          </div>
        </div>
        <Toggle on={cfg.enabled} onClick={() => set('enabled', !cfg.enabled)} />
      </div>

      {/* Triggers */}
      <div style={{ opacity: cfg.enabled ? 1 : 0.5 }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 0', borderTop: '1px solid var(--border-subtle)',
        }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>Notify on success</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>
              Send a message when a scan completes
            </div>
          </div>
          <Toggle on={cfg.on_success} onClick={() => { if (cfg.enabled) set('on_success', !cfg.on_success); }} />
        </div>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 0', borderTop: '1px solid var(--border-subtle)',
        }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>Notify on failure</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>
              Send a message when a scan fails
            </div>
          </div>
          <Toggle on={cfg.on_failure} onClick={() => { if (cfg.enabled) set('on_failure', !cfg.on_failure); }} />
        </div>
      </div>

      {/* Slack */}
      <div style={sectionStyle}>
        {channelHeader({
          title: 'Slack', hint: 'Incoming webhook posted to a channel',
          on: cfg.slack_enabled, onToggle: () => set('slack_enabled', !cfg.slack_enabled),
          channel: 'slack',
        })}
        {secretField({
          field: 'slack_webhook_url', label: 'Webhook URL',
          isSet: cfg.slack_webhook_url_set,
          placeholder: 'https://hooks.slack.com/services/...',
        })}
      </div>

      {/* Discord */}
      <div style={sectionStyle}>
        {channelHeader({
          title: 'Discord', hint: 'Channel webhook posted as an embed',
          on: cfg.discord_enabled, onToggle: () => set('discord_enabled', !cfg.discord_enabled),
          channel: 'discord',
        })}
        {secretField({
          field: 'discord_webhook_url', label: 'Webhook URL',
          isSet: cfg.discord_webhook_url_set,
          placeholder: 'https://discord.com/api/webhooks/...',
        })}
      </div>

      {/* Generic webhook */}
      <div style={sectionStyle}>
        {channelHeader({
          title: 'Generic Webhook', hint: 'JSON POST to your own endpoint',
          on: cfg.webhook_enabled, onToggle: () => set('webhook_enabled', !cfg.webhook_enabled),
          channel: 'webhook',
        })}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {secretField({
            field: 'webhook_url', label: 'Endpoint URL',
            isSet: cfg.webhook_url_set,
            placeholder: 'https://example.com/hooks/nous',
          })}
          {secretField({
            field: 'webhook_token', label: 'Bearer Token',
            isSet: cfg.webhook_token_set,
            placeholder: 'optional',
          })}
        </div>
      </div>

      {/* Telegram */}
      <div style={sectionStyle}>
        {channelHeader({
          title: 'Telegram', hint: 'Bot message sent to a chat',
          on: cfg.telegram_enabled, onToggle: () => set('telegram_enabled', !cfg.telegram_enabled),
          channel: 'telegram',
        })}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {secretField({
            field: 'telegram_bot_token', label: 'Bot Token',
            isSet: cfg.telegram_bot_token_set,
            placeholder: '123456:ABC-DEF...',
          })}
          <div>
            <div style={labelStyle}>Chat ID</div>
            <input
              value={cfg.telegram_chat_id}
              onChange={(e) => set('telegram_chat_id', e.target.value)}
              placeholder="-1001234567890"
              autoComplete="off"
              readOnly={!isAdmin}
              style={disabledInput()}
            />
          </div>
        </div>
      </div>

      {/* Tuning */}
      <div style={sectionStyle}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
          Delivery
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 14, fontFamily: 'var(--font-mono)' }}>
          Message detail and how hard each delivery is retried
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
          {TUNING.map(({ key, label, hint, min, max }) => (
            <div key={key}>
              <div style={labelStyle}>{label}</div>
              <input
                type="number"
                min={min}
                max={max}
                step={1}
                value={cfg[key]}
                onChange={(e) => set(key, clamp(Number(e.target.value), min, max))}
                readOnly={!isAdmin}
                style={disabledInput()}
              />
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6, fontFamily: 'var(--font-mono)' }}>{hint}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
