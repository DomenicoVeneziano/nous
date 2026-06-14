// frontend/src/api/settings.ts
import client from './client';
import type { User, UserCreate } from '../types/user';
import type { AssetSearchResult } from '../types/asset';

export async function fetchScanConfig(): Promise<Record<string, unknown>> {
  const { data } = await client.get('/settings/scan-config');
  return data;
}

export async function updateScanConfig(payload: Record<string, unknown>): Promise<void> {
  await client.put('/settings/scan-config', payload);
}

export async function saveFileContent(path: string, content: string): Promise<void> {
  await client.put('/files/content', { path, content });
}

export interface ProxyConfig {
  enabled: boolean;
  scheme: string;
  host: string;
  port: number;
  username: string;
  password_set: boolean;
  recon: boolean;
  tech: boolean;
  crawl: boolean;
}

export async function fetchProxyConfig(): Promise<ProxyConfig> {
  const { data } = await client.get<ProxyConfig>('/settings/proxy-config');
  return data;
}

export async function updateProxyConfig(payload: Partial<Omit<ProxyConfig, 'password_set'>> & { password?: string }): Promise<ProxyConfig> {
  const { data } = await client.put<ProxyConfig>('/settings/proxy-config', payload);
  return data;
}

export async function testProxyConfig(host: string, port: number): Promise<{ reachable: boolean; message: string }> {
  const { data } = await client.post<{ reachable: boolean; message: string }>('/settings/proxy-config/test', { host, port });
  return data;
}

export async function fetchUsers(): Promise<User[]> {
  const { data } = await client.get<User[]>('/settings/users');
  return data;
}

export async function createUser(payload: UserCreate): Promise<User> {
  const { data } = await client.post<User>('/settings/users', payload);
  return data;
}

export async function updateUser(id: string, payload: { username?: string; role?: string; password?: string }): Promise<User> {
  const { data } = await client.put<User>(`/settings/users/${id}`, payload);
  return data;
}

export async function deleteUser(id: string): Promise<void> {
  await client.delete(`/settings/users/${id}`);
}

export async function login(username: string, password: string): Promise<string> {
  const { data } = await client.post<{ access_token: string }>('/auth/login', { username, password });
  return data.access_token;
}

export async function searchAssets(query: string, projectId?: string): Promise<AssetSearchResult[]> {
  const { data } = await client.get('/search/', { params: { query, project_id: projectId } });
  return data;
}

export async function exportAssets(query: string, format: 'json' | 'csv', projectId?: string): Promise<void> {
  const params: Record<string, string> = { query, format };
  if (projectId) params.project_id = projectId;
  const { data } = await client.get('/search/export', { params, responseType: 'blob' });
  const mime = format === 'csv' ? 'text/csv' : 'application/json';
  const url = URL.createObjectURL(new Blob([data], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `export.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}
