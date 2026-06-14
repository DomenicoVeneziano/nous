// frontend/src/api/vulnPatterns.ts
import client from './client';
import type { VulnPattern, VulnPatternCreate, VulnPatternUpdate, VulnPatternTestResult } from '../types/vulnPattern';

export async function fetchVulnPatterns(): Promise<VulnPattern[]> {
  const { data } = await client.get<VulnPattern[]>('/vuln-patterns/');
  return data;
}

export async function createVulnPattern(payload: VulnPatternCreate): Promise<VulnPattern> {
  const { data } = await client.post<VulnPattern>('/vuln-patterns/', payload);
  return data;
}

export async function updateVulnPattern(id: string, payload: VulnPatternUpdate): Promise<VulnPattern> {
  const { data } = await client.put<VulnPattern>(`/vuln-patterns/${id}`, payload);
  return data;
}

export async function deleteVulnPattern(id: string): Promise<void> {
  await client.delete(`/vuln-patterns/${id}`);
}

export async function testVulnPattern(id: string, projectId: string): Promise<VulnPatternTestResult> {
  const { data } = await client.post<VulnPatternTestResult>(`/vuln-patterns/${id}/test`, null, {
    params: { project_id: projectId },
  });
  return data;
}
