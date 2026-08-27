// frontend/src/types/project.ts
export type ScheduleUnit = 'hours' | 'days' | 'weeks' | 'months';
export type ScanPhase = 'recon' | 'tech' | 'crawl';

export interface Project {
  id: string;
  title: string;
  description: string | null;
  icon: string | null;
  logo_path: string | null;
  root_domains: string[];
  subdomains: string[];
  status: 'to_scan' | 'scanning' | 'scanned';
  last_scan_date: string | null;
  last_scan_duration_s: number | null;
  asset_count: number;
  tech_count: number;
  is_master: boolean;
  schedule_enabled: boolean;
  schedule_interval_value: number | null;
  schedule_interval_unit: ScheduleUnit | null;
  schedule_phases: ScanPhase[] | null;
  // Naive UTC, same wire format as last_scan_date — parse with parseBackendDate.
  next_scan_at: string | null;
  schedule_last_run_at: string | null;
  // While a scheduled cycle is queued or running the server withholds
  // next_scan_at, so this flag is the only signal that one is in flight.
  schedule_cycle_active: boolean;
}

export interface ProjectCreate {
  title: string;
  description?: string;
  root_domains: string[];
  subdomains?: string[];
  schedule_enabled?: boolean;
  schedule_interval_value?: number;
  schedule_interval_unit?: ScheduleUnit;
  schedule_phases?: ScanPhase[];
}

export interface ProjectUpdate {
  title?: string;
  description?: string;
  root_domains?: string[];
  subdomains?: string[];
  status?: string;
  schedule_enabled?: boolean;
  schedule_interval_value?: number;
  schedule_interval_unit?: ScheduleUnit;
  schedule_phases?: ScanPhase[];
}
