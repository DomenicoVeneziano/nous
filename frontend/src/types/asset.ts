// frontend/src/types/asset.ts
export interface Highlight {
  field: string;
  source: string;
  snippet: string;
  start: number;
  end: number;
  index: number | null;
}

export interface AssetSearchResult extends Asset {
  highlights: Highlight[];
}

export interface CrawledUrls {
  crawling: string[];
  archived: string[];
}

export interface Asset {
  id: string;
  project_id: string;
  asset: string;
  asset_type: 'subdomain' | 'ip';
  dns_records: Record<string, unknown>[];
  technologies: string[];
  status_code: number | null;
  title: string | null;
  content_length: number | null;
  redirects_to: string | null;
  response_file_path: string | null;
  screenshot_path: string | null;
  crawled_urls: CrawledUrls;
  date_scanned: string | null;
  manually_inserted: boolean;
}

export interface AssetCreate {
  asset: string;
  asset_type?: 'subdomain' | 'ip';
  technologies?: string[];
  status_code?: number;
  title?: string;
  content_length?: number;
  dns_records?: Record<string, unknown>[];
  crawled_urls?: CrawledUrls;
}

export interface AssetUpdate {
  asset?: string;
  asset_type?: 'subdomain' | 'ip';
  technologies?: string[];
  status_code?: number | null;
  title?: string | null;
  content_length?: number | null;
  dns_records?: Record<string, unknown>[];
  crawled_urls?: CrawledUrls;
}
