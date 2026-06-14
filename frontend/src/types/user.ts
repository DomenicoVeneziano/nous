// frontend/src/types/user.ts
export interface User {
  id: string;
  username: string;
  role: 'admin' | 'viewer';
}

export interface UserCreate {
  username: string;
  password: string;
  role: 'admin' | 'viewer';
}
