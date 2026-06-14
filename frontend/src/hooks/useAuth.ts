// frontend/src/hooks/useAuth.ts
import { useAuthStore } from '../store/authStore';
import { login as apiLogin } from '../api/settings';
import { useCallback } from 'react';

export function useAuth() {
  const { token, role, setAuth, logout } = useAuthStore();

  const login = useCallback(async (username: string, password: string) => {
    const accessToken = await apiLogin(username, password);
    // Decode JWT payload to get role
    const payload = JSON.parse(atob(accessToken.split('.')[1]));
    setAuth(accessToken, payload.role, payload.sub);
  }, [setAuth]);

  return {
    token,
    role,
    isAdmin: role === 'admin',
    isAuthenticated: !!token,
    login,
    logout,
  };
}
