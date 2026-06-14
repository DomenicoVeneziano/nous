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
