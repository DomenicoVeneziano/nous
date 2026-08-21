// frontend/src/types/asset.ts
import type { Tag } from './tag';

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
  date_scanned: string | null; // last tech analysis
  first_seen: string | null;
  last_crawl_at: string | null;
  tags: Tag[];
  /** Derived server-side: first seen by the project's most recent recon job. */
  is_new: boolean;
}

export interface AssetCreate {
  asset: string;
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
