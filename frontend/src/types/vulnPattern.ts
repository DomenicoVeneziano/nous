// frontend/src/types/vulnPattern.ts
export interface VulnPatternCheck {
  field: string;
  regex: string;
}

export interface VulnPattern {
  id: string;
  name: string;
  description: string;
  checks: VulnPatternCheck[];
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface VulnPatternCreate {
  name: string;
  description: string;
  checks: VulnPatternCheck[];
}

export interface VulnPatternUpdate {
  description?: string;
  checks?: VulnPatternCheck[];
}

export interface VulnPatternTestResult {
  pattern_id: string;
  pattern_name: string;
  match_count: number;
  matched_asset_ids: string[];
}
