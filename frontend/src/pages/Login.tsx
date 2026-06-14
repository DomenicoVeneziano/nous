// frontend/src/pages/Login.tsx
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { Shield } from 'lucide-react';
import { DottedSurface } from '../components/ui/dotted-surface';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      navigate('/');
    } catch {
      setError('Invalid credentials');
    } finally {
      setLoading(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'var(--bg-base)',
    border: '1px solid var(--border-default)',
    borderRadius: 6, color: 'var(--text-primary)', padding: '11px 14px', fontSize: 13, outline: 'none',
    transition: 'border-color var(--transition-fast), box-shadow var(--transition-fast)',
  };

  return (
    <div style={{
      height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <DottedSurface />
      <form onSubmit={handleSubmit} style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)', borderRadius: 'var(--radius-xl)',
        padding: 36, width: 400,
        boxShadow: 'var(--shadow-elevated)',
        position: 'relative', overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 1,
          background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent)',
        }} />

        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{
            filter: 'drop-shadow(0 0 12px rgba(255,255,255,0.15))',
            display: 'inline-flex',
          }}>
            <Shield size={36} color="var(--accent-primary)" />
          </div>
          <h1 style={{
            color: 'var(--text-primary)',
            fontSize: 22, fontWeight: 700, marginTop: 10,
            letterSpacing: '0.04em',
          }}>Nous</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 4, fontFamily: 'var(--font-mono)' }}>
            Attack Surface Management
          </p>
        </div>

        <div style={{ marginBottom: 18 }}>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>
            Username
          </label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} style={inputStyle} />
        </div>
        <div style={{ marginBottom: 22 }}>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>
            Password
          </label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={inputStyle} />
        </div>

        {error && (
          <div style={{
            color: 'var(--status-error)', fontSize: 12, marginBottom: 14,
            background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)',
            padding: '8px 12px', borderRadius: 6, fontFamily: 'var(--font-mono)',
          }}>{error}</div>
        )}

        <button type="submit" disabled={loading} style={{
          width: '100%',
          background: 'var(--accent-primary)',
          color: '#000', border: '1px solid var(--accent-dim)',
          borderRadius: 6, padding: '11px 0', fontSize: 13, fontWeight: 600,
          cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
          boxShadow: 'var(--accent-glow)',
          transition: 'all var(--transition-fast)',
          letterSpacing: '0.02em',
        }}>
          {loading ? 'Signing in...' : 'Sign In'}
        </button>
      </form>
    </div>
  );
}
