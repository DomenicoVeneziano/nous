// frontend/src/types/finding.ts
export type Severity = 'informative' | 'low' | 'medium' | 'high' | 'critical';

export interface Finding {
  id: string;
  asset_id: string;
  project_id: string;
  title: string;
  severity: Severity;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface FindingCreate {
  title: string;
  severity: Severity;
  body: string;
}

export interface FindingUpdate {
  title?: string;
  severity?: Severity;
  body?: string;
}

export interface FindingSearchResult extends Finding {
  asset_hostname: string;
}
