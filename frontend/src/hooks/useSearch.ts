// frontend/src/hooks/useSearch.ts
import { useState, useCallback, useRef } from 'react';
import { searchAssets } from '../api/settings';
import type { AssetSearchResult } from '../types/asset';

export function useSearch() {
  const [results, setResults] = useState<AssetSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const search = useCallback((q: string, projectId?: string) => {
    setQuery(q);

    if (timerRef.current) clearTimeout(timerRef.current);

    if (!q.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    timerRef.current = setTimeout(async () => {
      try {
        const data = await searchAssets(q, projectId);
        setResults(data);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  }, []);

  return { results, loading, query, search };
}
