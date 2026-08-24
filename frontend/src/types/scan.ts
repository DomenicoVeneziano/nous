// frontend/src/types/scan.ts
export interface ScanJob {
  id: string;
  project_id: string;
  scan_type: 'recon' | 'tech' | 'crawl';
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'timed_out';
  queue_pos: number | null;
  asset_ids: string[] | null;
  scope_domains: string[] | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  log_path: string | null;
  error_msg: string | null;
}

export interface ScanCreate {
  project_id: string;
  scan_type: 'recon' | 'tech' | 'crawl';
  asset_ids?: string[];
  scope_domains?: string[];
}

// Snapshot of a multi-pass scan's progress, broadcast as a `scan_progress`
// event. Note that `assets_total` is not fixed for the life of a job: it grows
// at pass boundaries, as each retry candidate set only becomes known once the
// preceding pass finishes. Consumers must re-read it on every snapshot.
export interface ScanProgress {
  job_id: string;
  scan_type: string;
  pass_index: number;
  pass_total: number;
  pass_label: string;
  assets_done: number;
  assets_total: number;
  pass_assets_done: number;
  pass_assets_total: number;
}
