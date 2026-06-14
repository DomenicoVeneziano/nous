// frontend/src/types/project.ts
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
}

export interface ProjectCreate {
  title: string;
  description?: string;
  root_domains: string[];
  subdomains?: string[];
}

export interface ProjectUpdate {
  title?: string;
  description?: string;
  root_domains?: string[];
  subdomains?: string[];
  status?: string;
}
