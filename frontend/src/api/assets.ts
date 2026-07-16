// frontend/src/api/assets.ts
import client from './client';
import type { Asset, AssetCreate, AssetUpdate } from '../types/asset';

export async function fetchAssets(projectId: string, limit = 500, offset = 0): Promise<Asset[]> {
  const { data } = await client.get<Asset[]>(`/projects/${projectId}/assets/`, {
    params: { limit, offset },
  });
  return data;
}

// Fetch every asset for a project by paging through the backend until a short
// page signals the end. No fixed cap — a project with tens of thousands of
// assets is loaded in full.
export async function fetchAllAssets(projectId: string): Promise<Asset[]> {
  const PAGE = 2000;
  const all: Asset[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const page = await fetchAssets(projectId, PAGE, offset);
    all.push(...page);
    if (page.length < PAGE) break;
  }
  return all;
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

/**
 * Download an asset's full detail as a formatted `<asset>.json` file. The
 * request is authenticated via the shared client, so we fetch the blob and
 * drive the browser download from an object URL rather than a bare link.
 */
export async function exportAsset(projectId: string, assetId: string, assetName: string): Promise<void> {
  const { data } = await client.get(`/projects/${projectId}/assets/${assetId}/export`, {
    responseType: 'blob',
  });
  const url = URL.createObjectURL(data as Blob);
  const safeName = assetName.replace(/[^A-Za-z0-9._-]/g, '_') || 'asset';
  const a = document.createElement('a');
  a.href = url;
  a.download = `${safeName}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
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
