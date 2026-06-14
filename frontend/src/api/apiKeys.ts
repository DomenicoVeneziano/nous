// frontend/src/api/apiKeys.ts
import client from './client';
import type { ApiKey, ApiKeyCreated, ApiKeyCreateRequest, ApiKeyRenameRequest } from '../types/apiKey';

export async function fetchApiKeys(): Promise<ApiKey[]> {
  const { data } = await client.get<ApiKey[]>('/api-keys/');
  return data;
}

export async function createApiKey(payload: ApiKeyCreateRequest): Promise<ApiKeyCreated> {
  const { data } = await client.post<ApiKeyCreated>('/api-keys/', payload);
  return data;
}

export async function renameApiKey(id: string, payload: ApiKeyRenameRequest): Promise<ApiKey> {
  const { data } = await client.patch<ApiKey>(`/api-keys/${id}`, payload);
  return data;
}

export async function deleteApiKey(id: string): Promise<void> {
  await client.delete(`/api-keys/${id}`);
}
