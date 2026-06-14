// frontend/src/api/scans.ts
import client from './client';
import type { ScanJob, ScanCreate } from '../types/scan';

export async function enqueueScan(payload: ScanCreate): Promise<ScanJob> {
  const { data } = await client.post<ScanJob>('/scans/', payload);
  return data;
}

export async function fetchQueue(): Promise<ScanJob[]> {
  const { data } = await client.get<ScanJob[]>('/scans/queue');
  return data;
}

export async function fetchHistory(): Promise<ScanJob[]> {
  const { data } = await client.get<ScanJob[]>('/scans/history');
  return data;
}

export async function reorderJob(jobId: string, queuePos: number): Promise<ScanJob> {
  const { data } = await client.patch<ScanJob>(`/scans/${jobId}/position`, { queue_pos: queuePos });
  return data;
}

export async function cancelJob(jobId: string): Promise<void> {
  await client.delete(`/scans/${jobId}`);
}

export async function clearHistory(): Promise<void> {
  await client.delete('/scans/history');
}

export async function clearScanOutput(): Promise<void> {
  await client.delete('/scans/output');
}
