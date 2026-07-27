// frontend/src/api/tags.ts
import client from './client';
import type { Asset } from '../types/asset';
import type { Tag, TagCreate, TagUpdate, TagWithCount } from '../types/tag';

export async function fetchTags(projectId: string): Promise<TagWithCount[]> {
  const { data } = await client.get<TagWithCount[]>(`/projects/${projectId}/tags`);
  return data;
}

export async function createTag(projectId: string, payload: TagCreate): Promise<Tag> {
  const { data } = await client.post<Tag>(`/projects/${projectId}/tags`, payload);
  return data;
}

export async function updateTag(projectId: string, tagId: string, payload: TagUpdate): Promise<Tag> {
  const { data } = await client.put<Tag>(`/projects/${projectId}/tags/${tagId}`, payload);
  return data;
}

export async function deleteTag(projectId: string, tagId: string): Promise<void> {
  await client.delete(`/projects/${projectId}/tags/${tagId}`);
}

/**
 * Attach a tag to an asset. Pass `name` to create-and-attach in one call — the
 * tag entry field relies on that so a new label needs no separate create step.
 * Returns the updated asset so the caller can refresh its chips directly.
 */
export async function attachTag(
  projectId: string,
  assetId: string,
  payload: { tag_id?: string; name?: string; color?: string | null },
): Promise<Asset> {
  const { data } = await client.post<Asset>(`/projects/${projectId}/assets/${assetId}/tags`, payload);
  return data;
}

export async function detachTag(projectId: string, assetId: string, tagId: string): Promise<Asset> {
  const { data } = await client.delete<Asset>(`/projects/${projectId}/assets/${assetId}/tags/${tagId}`);
  return data;
}
