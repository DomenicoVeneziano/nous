// frontend/src/api/findings.ts
import client from './client';
import type { Finding, FindingCreate, FindingUpdate, FindingSearchResult } from '../types/finding';

const base = (projectId: string, assetId: string) =>
  `/projects/${projectId}/assets/${assetId}/findings`;

export async function fetchFindings(projectId: string, assetId: string): Promise<Finding[]> {
  const { data } = await client.get<Finding[]>(base(projectId, assetId) + '/');
  return data;
}

export async function createFinding(projectId: string, assetId: string, payload: FindingCreate): Promise<Finding> {
  const { data } = await client.post<Finding>(base(projectId, assetId) + '/', payload);
  return data;
}

export async function updateFinding(
  projectId: string,
  assetId: string,
  findingId: string,
  payload: FindingUpdate,
): Promise<Finding> {
  const { data } = await client.put<Finding>(`${base(projectId, assetId)}/${findingId}`, payload);
  return data;
}

export async function deleteFinding(projectId: string, assetId: string, findingId: string): Promise<void> {
  await client.delete(`${base(projectId, assetId)}/${findingId}`);
}

export async function searchFindings(params: {
  query?: string;
  severity?: string;
  project_id?: string;
  limit?: number;
  offset?: number;
}): Promise<FindingSearchResult[]> {
  const { data } = await client.get<FindingSearchResult[]>('/search/findings', { params });
  return data;
}
