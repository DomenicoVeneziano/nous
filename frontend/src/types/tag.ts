// frontend/src/types/tag.ts

/**
 * Tags come in two kinds, separated by `is_system`:
 *   - system tags record how an asset was discovered (Passive, Bruteforce,
 *     Permutations, Crawling, Redirect, Manual, Seed). They accumulate and are
 *     read-only — the API rejects edits, the UI just doesn't offer them.
 *   - user tags are free-form triage labels under full CRUD.
 *
 * "New!" is neither: it is derived server-side from the asset's first_seen scan
 * and surfaces as `Asset.is_new`, so it never appears in this list.
 */
export interface Tag {
  id: string;
  project_id: string;
  name: string;
  color: string | null;
  is_system: boolean;
}

export interface TagWithCount extends Tag {
  asset_count: number;
}

export interface TagCreate {
  name: string;
  color?: string | null;
}

export interface TagUpdate {
  name?: string;
  color?: string | null;
}

export const NEW_TAG_LABEL = 'New!';
