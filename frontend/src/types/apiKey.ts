// frontend/src/types/apiKey.ts
export interface ApiKey {
  id: string;
  name: string;
  key_type: 'edit' | 'view';
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  is_active: boolean;
}

export interface ApiKeyCreated extends ApiKey {
  full_key: string;
}

export interface ApiKeyCreateRequest {
  name: string;
  key_type: 'edit' | 'view';
}

export interface ApiKeyRenameRequest {
  name: string;
}
