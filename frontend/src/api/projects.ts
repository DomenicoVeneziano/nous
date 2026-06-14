// frontend/src/api/projects.ts
import client from './client';
import type { Project, ProjectCreate, ProjectUpdate } from '../types/project';

export async function fetchProjects(): Promise<Project[]> {
  const { data } = await client.get<Project[]>('/projects/');
  return data;
}

export async function fetchProject(id: string): Promise<Project> {
  const { data } = await client.get<Project>(`/projects/${id}`);
  return data;
}

export async function createProject(payload: ProjectCreate): Promise<Project> {
  const { data } = await client.post<Project>('/projects/', payload);
  return data;
}

export async function updateProject(id: string, payload: ProjectUpdate): Promise<Project> {
  const { data } = await client.put<Project>(`/projects/${id}`, payload);
  return data;
}

export async function deleteProject(id: string): Promise<void> {
  await client.delete(`/projects/${id}`);
}

export async function bulkDeleteProjects(projectIds: string[]): Promise<{ deleted: number }> {
  const { data } = await client.post<{ deleted: number }>('/projects/bulk-delete', { project_ids: projectIds });
  return data;
}

export async function uploadProjectIcon(projectId: string, file: File): Promise<{ icon: string }> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await client.post<{ icon: string }>(`/projects/${projectId}/icon`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function deleteProjectIcon(projectId: string): Promise<void> {
  await client.delete(`/projects/${projectId}/icon`);
}

// Project icons are served from an authenticated endpoint, so a raw <img src>
// can't load them (the browser won't send the bearer token). Fetch the bytes
// through the API client and hand back an object URL instead. Caller owns
// revoking the returned URL.
export async function fetchProjectIconUrl(projectId: string): Promise<string> {
  const { data } = await client.get(`/projects/${projectId}/icon`, {
    responseType: 'blob',
  });
  return URL.createObjectURL(data as Blob);
}
