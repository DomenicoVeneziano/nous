// frontend/src/components/settings/UserManagement.tsx
import React, { useEffect, useState } from 'react';
import type { User } from '../../types/user';
import { fetchUsers, createUser, updateUser, deleteUser } from '../../api/settings';
import ConfirmModal from '../shared/ConfirmModal';
import { Pencil, Check, X } from 'lucide-react';

// Deterministic grey shade from string
function avatarColor(str: string): string {
  const greys = ['#808080', '#6e6e6e', '#929292', '#a4a4a4', '#5c5c5c', '#b0b0b0', '#505050', '#bcbcbc'];
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  return greys[Math.abs(hash) % greys.length];
}

interface EditState {
  username: string;
  password: string;
}

const primaryBtnStyle: React.CSSProperties = {
  background: 'var(--accent-primary)',
  color: 'var(--bg-base)',
  border: '1px solid var(--accent-dim)',
  borderRadius: 6, padding: '7px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
  transition: 'all var(--transition-fast)', whiteSpace: 'nowrap' as const,
};

export default function UserManagement() {
  const [users, setUsers] = useState<User[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<'admin' | 'viewer'>('viewer');
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editState, setEditState] = useState<EditState>({ username: '', password: '' });
  const [editError, setEditError] = useState('');

  const load = () => fetchUsers().then(setUsers).catch(() => {});

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    if (!newUsername || !newPassword) return;
    await createUser({ username: newUsername, password: newPassword, role: newRole });
    setNewUsername(''); setNewPassword(''); setShowCreate(false);
    load();
  };

  const handleRoleChange = async (id: string, role: 'admin' | 'viewer') => {
    await updateUser(id, { role });
    load();
  };

  const handleDelete = async () => {
    if (deleteId) {
      await deleteUser(deleteId);
      setDeleteId(null);
      load();
    }
  };

  const startEdit = (user: User) => {
    setEditingId(user.id);
    setEditState({ username: user.username, password: '' });
    setEditError('');
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditState({ username: '', password: '' });
    setEditError('');
  };

  const saveEdit = async (userId: string) => {
    setEditError('');
    const payload: { username?: string; password?: string } = {};
    const user = users.find((u) => u.id === userId);
    if (!user) return;
    if (editState.username && editState.username !== user.username) {
      payload.username = editState.username;
    }
    if (editState.password) {
      payload.password = editState.password;
    }
    if (Object.keys(payload).length === 0) {
      cancelEdit();
      return;
    }
    try {
      await updateUser(userId, payload);
      cancelEdit();
      load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setEditError(msg || 'Failed to update');
    }
  };

  const thStyle: React.CSSProperties = {
    background: 'var(--bg-elevated)', color: 'var(--text-muted)',
    fontSize: 11, fontWeight: 600,
    textTransform: 'uppercase', letterSpacing: '0.06em',
    padding: '12px 16px', textAlign: 'left',
    borderBottom: '1px solid var(--border-default)',
  };

  const tdStyle: React.CSSProperties = {
    padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', fontSize: 14,
  };

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-base)', border: '1px solid var(--border-default)',
    borderRadius: 6, color: 'var(--text-primary)', padding: '8px 12px', fontSize: 13,
    outline: 'none', transition: 'border-color var(--transition-fast), box-shadow var(--transition-fast)',
  };

  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
      borderRadius: 8, overflow: 'hidden',
      boxShadow: 'var(--shadow-card), inset 0 1px 0 rgba(255,255,255,0.02)',
    }}>
      <div style={{
        padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>Users</span>
        <button onClick={() => setShowCreate(!showCreate)} style={primaryBtnStyle}>Add User</button>
      </div>

      {showCreate && (
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)',
          display: 'flex', gap: 10, alignItems: 'center',
          background: 'var(--bg-elevated)',
        }}>
          <input value={newUsername} onChange={(e) => setNewUsername(e.target.value)} placeholder="Username" style={inputStyle} />
          <input value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="Password" type="password" style={inputStyle} />
          <select value={newRole} onChange={(e) => setNewRole(e.target.value as 'admin' | 'viewer')} style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }}>
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
          <button onClick={handleCreate} style={primaryBtnStyle}>Create</button>
        </div>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={thStyle}>User</th>
            <th style={thStyle}>Role</th>
            <th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u, i) => {
            const color = avatarColor(u.username);
            const initials = u.username.slice(0, 2).toUpperCase();
            const isEditing = editingId === u.id;
            return (
              <tr
                key={u.id}
                style={{
                  background: isEditing ? 'var(--bg-selected)' : (i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)'),
                  transition: 'background var(--transition-fast)',
                }}
                onMouseEnter={(e) => { if (!isEditing) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                onMouseLeave={(e) => { if (!isEditing) e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)'; }}
              >
                <td style={tdStyle}>
                  {isEditing ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{
                          width: 30, height: 30, borderRadius: '50%',
                          background: 'var(--bg-elevated)',
                          border: '1px solid var(--border-default)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 11, fontWeight: 600, color, fontFamily: 'var(--font-mono)',
                          flexShrink: 0,
                        }}>
                          {initials}
                        </div>
                        <input
                          value={editState.username}
                          onChange={(e) => setEditState((s) => ({ ...s, username: e.target.value }))}
                          style={{ ...inputStyle, flex: 1, fontSize: 13 }}
                          placeholder="Username"
                        />
                      </div>
                      <input
                        value={editState.password}
                        onChange={(e) => setEditState((s) => ({ ...s, password: e.target.value }))}
                        style={{ ...inputStyle, fontSize: 13, marginLeft: 38 }}
                        placeholder="New password (leave empty to keep)"
                        type="password"
                      />
                      {editError && (
                        <div style={{
                          fontSize: 12, color: 'var(--status-error)', marginLeft: 38,
                          fontFamily: 'var(--font-mono)',
                        }}>{editError}</div>
                      )}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{
                        width: 30, height: 30, borderRadius: '50%',
                        background: 'var(--bg-elevated)',
                        border: '1px solid var(--border-default)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 11, fontWeight: 600, color, fontFamily: 'var(--font-mono)',
                      }}>
                        {initials}
                      </div>
                      <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-code)', fontWeight: 500, fontSize: 14 }}>
                        {u.username}
                      </span>
                    </div>
                  )}
                </td>
                <td style={tdStyle}>
                  <span style={{
                    fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 600,
                    letterSpacing: '0.06em',
                    padding: '4px 10px', borderRadius: 4,
                    background: u.role === 'admin' ? 'var(--accent-subtle)' : 'var(--status-muted-bg)',
                    color: u.role === 'admin' ? 'var(--accent-primary)' : 'var(--text-muted)',
                    border: u.role === 'admin' ? '1px solid var(--accent-border)' : '1px solid var(--status-muted-border)',
                  }}>
                    {u.role.toUpperCase()}
                  </span>
                  <select
                    value={u.role}
                    onChange={(e) => handleRoleChange(u.id, e.target.value as 'admin' | 'viewer')}
                    style={{ ...inputStyle, fontSize: 13, marginLeft: 10, fontFamily: 'var(--font-mono)' }}
                  >
                    <option value="admin">admin</option>
                    <option value="viewer">viewer</option>
                  </select>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    {isEditing ? (
                      <>
                        <button onClick={() => saveEdit(u.id)} title="Save" style={{
                          background: 'var(--status-success-bg)',
                          color: 'var(--status-success)',
                          border: '1px solid var(--status-success-border)',
                          borderRadius: 5, padding: '5px 8px', cursor: 'pointer',
                          display: 'flex', alignItems: 'center',
                          transition: 'all var(--transition-fast)',
                        }}>
                          <Check size={13} />
                        </button>
                        <button onClick={cancelEdit} title="Cancel" style={{
                          background: 'var(--status-muted-bg)',
                          color: '#5c5c5c',
                          border: '1px solid var(--status-muted-border)',
                          borderRadius: 5, padding: '5px 8px', cursor: 'pointer',
                          display: 'flex', alignItems: 'center',
                          transition: 'all var(--transition-fast)',
                        }}>
                          <X size={13} />
                        </button>
                      </>
                    ) : (
                      <button onClick={() => startEdit(u)} title="Edit" style={{
                        background: 'var(--bg-elevated)',
                        color: 'var(--text-secondary)',
                        border: '1px solid var(--border-default)',
                        borderRadius: 5, padding: '5px 8px', cursor: 'pointer',
                        display: 'flex', alignItems: 'center',
                        transition: 'all var(--transition-fast)',
                      }}
                        onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.2)'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.filter = 'brightness(1)'; }}
                      >
                        <Pencil size={13} />
                      </button>
                    )}
                    <button onClick={() => setDeleteId(u.id)} style={{
                      background: 'var(--status-error-bg)',
                      color: 'var(--status-error)',
                      border: '1px solid var(--status-error-border)',
                      borderRadius: 5, padding: '5px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                      fontFamily: 'var(--font-mono)', letterSpacing: '0.04em',
                      transition: 'all var(--transition-fast)',
                    }}
                      onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.2)'; }}
                      onMouseLeave={(e) => { e.currentTarget.style.filter = 'brightness(1)'; }}
                    >Delete</button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <ConfirmModal
        open={!!deleteId}
        title="Delete User"
        message="Are you sure you want to delete this user?"
        onConfirm={handleDelete}
        onCancel={() => setDeleteId(null)}
        destructive
      />
    </div>
  );
}
