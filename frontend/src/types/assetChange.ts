// frontend/src/types/assetChange.ts

/** The asset columns the engine tracks between scans. */
export type AssetChangeField =
  | 'status_code'
  | 'title'
  | 'redirects_to'
  | 'content_length'
  | 'technologies'
  | 'dns_records';

/**
 * One recorded change to a single asset field.
 *
 * For the scalar fields both value columns hold a plain text value (or null).
 * For the set-valued fields (`technologies`, `dns_records`) the pair is a delta
 * rather than a before/after: `old_value` is a JSON array of removed entries and
 * `new_value` a JSON array of added ones, either of which may be null or empty.
 */
export interface AssetChange {
  id: string;
  asset_id: string;
  project_id: string;
  scan_id: string | null;
  field: AssetChangeField;
  old_value: string | null;
  new_value: string | null;
  changed_at: string;
}

export interface AssetChangePage {
  items: AssetChange[];
  next_cursor: string | null;
}
