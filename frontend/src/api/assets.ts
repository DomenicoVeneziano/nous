// frontend/src/api/assets.ts
import client from './client';
import type { Asset, AssetCreate, AssetUpdate } from '../types/asset';

export async function fetchAssets(projectId: string, limit = 500, offset = 0): Promise<Asset[]> {
  const { data } = await client.get<Asset[]>(`/projects/${projectId}/assets/`, {
    params: { limit, offset },
  });
  return data;
}

export async function fetchAsset(projectId: string, assetId: string): Promise<Asset> {
  const { data } = await client.get<Asset>(`/projects/${projectId}/assets/${assetId}`);
  return data;
}

export async function createAsset(projectId: string, payload: AssetCreate): Promise<Asset> {
  const { data } = await client.post<Asset>(`/projects/${projectId}/assets/`, payload);
  return data;
}

export async function updateAsset(projectId: string, assetId: string, payload: AssetUpdate): Promise<Asset> {
  const { data } = await client.put<Asset>(`/projects/${projectId}/assets/${assetId}`, payload);
  return data;
}

export async function deleteAsset(projectId: string, assetId: string): Promise<void> {
  await client.delete(`/projects/${projectId}/assets/${assetId}`);
}

export async function deleteAssetScreenshot(projectId: string, assetId: string): Promise<void> {
  await client.delete(`/projects/${projectId}/assets/${assetId}/screenshot`);
}

export async function countAssets(projectId: string): Promise<number> {
  const { data } = await client.get<{ count: number }>(`/projects/${projectId}/assets/count`);
  return data.count;
}

export async function fetchTechDistribution(): Promise<{ name: string; count: number }[]> {
  const { data } = await client.get<{ name: string; count: number }[]>('/stats/technologies');
  return data;
}

/**
 * Fetch a screenshot (or any project image) as an authenticated blob and return
 * an object URL. Callers are responsible for revoking the URL when done.
 */
export async function fetchImageObjectUrl(path: string): Promise<string> {
  const { data } = await client.get('/files/image', {
    params: { path },
    responseType: 'blob',
  });
  return URL.createObjectURL(data as Blob);
}
