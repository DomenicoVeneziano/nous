// frontend/src/store/authStore.ts
import { create } from 'zustand';

interface AuthState {
  token: string | null;
  role: 'admin' | 'viewer' | null;
  userId: string | null;
  setAuth: (token: string, role: 'admin' | 'viewer', userId: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('nous_token'),
  role: (localStorage.getItem('nous_role') as 'admin' | 'viewer') || null,
  userId: localStorage.getItem('nous_user_id'),

  setAuth: (token, role, userId) => {
    localStorage.setItem('nous_token', token);
    localStorage.setItem('nous_role', role);
    localStorage.setItem('nous_user_id', userId);
    set({ token, role, userId });
  },

  logout: () => {
    localStorage.removeItem('nous_token');
    localStorage.removeItem('nous_role');
    localStorage.removeItem('nous_user_id');
    set({ token: null, role: null, userId: null });
  },
}));
