// frontend/src/pages/ProjectView.tsx
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { fetchAllAssets, fetchAsset, createAsset, deleteAsset } from '../api/assets';
import { enqueueScan } from '../api/scans';
import type { Asset, AssetCreate, AssetSearchResult } from '../types/asset';
import ProjectHeader from '../components/project/ProjectHeader';
import SearchBar from '../components/project/SearchBar';
import AssetTable from '../components/project/AssetTable';
import AssetDetail from '../components/project/AssetDetail';
import TechPieChart from '../components/project/TechPieChart';
import BulkActionsMenu from '../components/projects/BulkActionsMenu';
import ProjectEditOverlay from '../components/projects/ProjectEditOverlay';
import ReconScopeModal from '../components/project/ReconScopeModal';
import FindingsSearchView from '../components/project/FindingsSearchView';
import ScreenshotsView from '../components/project/ScreenshotsView';
import TagManager from '../components/project/TagManager';
import { useSearch } from '../hooks/useSearch';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAuth } from '../hooks/useAuth';
import { Plus, Tags } from 'lucide-react';

type ProjectTab = 'assets' | 'screenshots' | 'findings';

const LINE_RE = /^(\S+)(?:\s+\[(\d+)\])?(?:\s+\[([^\]]+)\])?(?:\s+\[(\d+)\])?(?:\s+\[([^\]]+)\])?$/;

function parseLine(raw: string): AssetCreate {
  const trimmed = raw.trim();
  const match = trimmed.match(LINE_RE);
  if (!match) return { asset: trimmed };
  const [, hostname, statusRaw, titleRaw, lengthRaw, techRaw] = match;
  const payload: AssetCreate = { asset: hostname };
  if (statusRaw !== undefined) payload.status_code = parseInt(statusRaw, 10);
  if (titleRaw !== undefined) payload.title = titleRaw.trim();
  if (lengthRaw !== undefined) payload.content_length = parseInt(lengthRaw, 10);
  if (techRaw !== undefined) payload.technologies = techRaw.split(',').map((t) => t.trim()).filter(Boolean);
  return payload;
}

/** Re-seat a displayed asset on a freshly returned row, carrying its search
 *  highlights across: the asset endpoints return plain assets, so dropping them
 *  would blank every match in the panel and in the table row. */
function withHighlights(prev: Asset, fresh: Asset): Asset {
  const { highlights } = prev as Partial<AssetSearchResult>;
  if (!highlights) return fresh;
  const merged: AssetSearchResult = { ...fresh, highlights };
  return merged;
}

/** Pull FastAPI's `detail` off a failed request so the operator sees the
 *  server's reason (a CIDR that expands past the cap, a duplicate hostname).
 *  `detail` is a string for an explicit HTTPException and a list of error
 *  objects for a pydantic-level 422, so both shapes are rendered; a
 *  transport-level failure falls back to the error's own message. */
function errorDetail(reason: unknown): string {
  const detail = (reason as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.flatMap((entry) => {
      const { msg, loc } = (entry ?? {}) as { msg?: unknown; loc?: unknown };
      if (typeof msg !== 'string') return [];
      // `loc` reads like ['body', 'asset']; only its tail names the field the
      // operator can act on, so the envelope prefix is dropped.
      const field = Array.isArray(loc) ? loc[loc.length - 1] : undefined;
      return [typeof field === 'string' || typeof field === 'number' ? `${field}: ${msg}` : msg];
    });
    if (parts.length > 0) return parts.join('; ');
  }
  if (reason instanceof Error && reason.message) return reason.message;
  return 'Request failed';
}

/** HTTP status of a failed request, when the failure reached the server at all. */
function errorStatus(reason: unknown): number | undefined {
  const status = (reason as { response?: { status?: unknown } })?.response?.status;
  return typeof status === 'number' ? status : undefined;
}

export default function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // Deep link from the global search bar: `/projects/:id?asset=<uuid>`. Kept in
  // the URL so the open panel survives a reload and a cross-project click,
  // which changes `:id` and re-runs the load effect below.
  const focusAssetId = searchParams.get('asset');
  const { current, loadProject, loadProjects } = useProjectStore();
  const [assets, setAssets] = useState<Asset[]>([]);
  // Distinguishes "the project's assets have not arrived yet" from "the id is
  // genuinely not in the set" — only the latter may take the fallback fetch.
  const [assetsLoaded, setAssetsLoaded] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [detailAsset, setDetailAsset] = useState<Asset | null>(null);
  const [showEdit, setShowEdit] = useState(false);
  const [showReconModal, setShowReconModal] = useState(false);
  const [showAddAsset, setShowAddAsset] = useState(false);
  const [showTagManager, setShowTagManager] = useState(false);
  const [newAssetValue, setNewAssetValue] = useState('');
  const [addingAsset, setAddingAsset] = useState(false);
  const [addErrors, setAddErrors] = useState<{ line: string; detail: string }[]>([]);
  const { results, loading: searchLoading, search, query } = useSearch();
  const assetUpdateTimer = useRef<ReturnType<typeof setTimeout>>();
  // Last id the fallback fetch was attempted for, so a missing asset costs one
  // request rather than one per asset reload.
  const fallbackFetchedRef = useRef<string | null>(null);
  const { isAdmin } = useAuth();
  const [activeTab, setActiveTab] = useState<ProjectTab>('assets');

  const loadAssets = useCallback(async (): Promise<Asset[]> => {
    if (!id) return [];
    const data = await fetchAllAssets(id);
    setAssets(data);
    setAssetsLoaded(true);
    return data;
  }, [id]);

  useEffect(() => {
    if (id) {
      setAssetsLoaded(false);
      loadProject(id);
      loadAssets();
    }
  }, [id]);

  // Open the deep-linked asset's panel. Intentionally not keyed on
  // `detailAsset`: the guard below reads it only to bail out, and adding it as
  // a dependency would re-run this on every panel change.
  useEffect(() => {
    if (!focusAssetId) return;
    // A row click writes `?asset=` too, and the object it hands over carries
    // the FTS highlights. Bailing out here keeps that richer object in place
    // instead of replacing it with the plain row re-derived from `assets`.
    if (detailAsset?.id === focusAssetId) return;

    // Every side effect below is deferred until a panel is actually about to
    // open: a run that reveals nothing must leave the tab and the query exactly
    // as the operator left them.
    const reveal = (row: Asset) => {
      setActiveTab('assets');
      // The table renders `results` while a project-scoped query is active, so
      // a stale query would hide the very row being linked to.
      search('');
      setDetailAsset(row);
    };

    const row = assets.find((a) => a.id === focusAssetId);
    if (row) {
      fallbackFetchedRef.current = null;
      reveal(row);
      return;
    }
    if (!assetsLoaded) return;
    // Not in the project's set: it may have been deleted, may belong to another
    // project, or the reload may simply be racing a WS update. One direct fetch
    // settles it.
    if (fallbackFetchedRef.current === focusAssetId) return;
    fallbackFetchedRef.current = focusAssetId;
    if (!id) return;
    fetchAsset(id, focusAssetId)
      .then((fresh) => reveal(fresh))
      .catch((err: unknown) => {
        // Only a 404 proves the asset is gone. A 401, a 5xx or a dropped
        // connection says nothing about it, and since the guard above blocks a
        // retry, dropping the parameter there would strand the deep link.
        if (errorStatus(err) === 404) setSearchParams({}, { replace: true });
      });
  }, [focusAssetId, assets, assetsLoaded]);

  useEffect(() => {
    return () => { clearTimeout(assetUpdateTimer.current); };
  }, []);

  useWebSocket({
    // Debounce asset_update so a burst of events (e.g. during an active scan or
    // on WS reconnect buffer replay) collapses into a single fetch.
    asset_update: () => {
      clearTimeout(assetUpdateTimer.current);
      assetUpdateTimer.current = setTimeout(() => loadAssets(), 1500);
    },
    job_complete: () => { loadAssets(); if (id) loadProject(id); },
  });

  const displayAssets: Asset[] = query ? results : assets;

  // Closing always strips `?asset` as well, otherwise a reload would reopen the
  // panel the operator just dismissed. `replace` keeps the back button pointing
  // at wherever they came from rather than at the same project twice.
  const closeDetail = useCallback(() => {
    setDetailAsset(null);
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  // A row click opens the panel directly with the clicked object (highlights
  // included) and mirrors it into the URL, so the two entry points leave the
  // page in the same state.
  const openDetail = useCallback((asset: Asset) => {
    setDetailAsset(asset);
    setSearchParams({ asset: asset.id }, { replace: true });
  }, [setSearchParams]);

  const handleSearch = (q: string) => search(q, id);

  const toggleSelect = (assetId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(assetId)) next.delete(assetId); else next.add(assetId);
      return next;
    });
  };

  const selectAll = () => {
    if (selectedIds.size === displayAssets.length) setSelectedIds(new Set());
    else setSelectedIds(new Set(displayAssets.map((a) => a.id)));
  };

  const runScan = async (type: 'recon' | 'tech' | 'crawl') => {
    if (!id) return;
    await enqueueScan({
      project_id: id,
      scan_type: type,
      asset_ids: type === 'recon' ? undefined : Array.from(selectedIds),
    });
    setSelectedIds(new Set());
  };

  const handleReconConfirm = async (selectedDomains: string[]) => {
    if (!id) return;
    setShowReconModal(false);
    await enqueueScan({
      project_id: id,
      scan_type: 'recon',
      scope_domains: selectedDomains,
    });
  };

  const handleAddAsset = async () => {
    if (!id || !newAssetValue.trim()) return;
    setAddingAsset(true);
    try {
      const lines = newAssetValue.split('\n').map((v) => v.trim()).filter(Boolean);
      const outcomes = await Promise.allSettled(lines.map((line) => createAsset(id, parseLine(line))));
      // Each line is submitted independently, so a rejected one is reported
      // next to its own input instead of being swallowed: an oversized CIDR
      // fails with the server's own explanation and the rest still land.
      const failures = outcomes.flatMap((outcome, idx) => (
        outcome.status === 'rejected'
          ? [{ line: lines[idx], detail: errorDetail(outcome.reason) }]
          : []
      ));
      setAddErrors(failures);
      // The form stays open while anything failed so the errors remain on
      // screen next to the text that produced them.
      if (failures.length === 0) {
        setNewAssetValue('');
        setShowAddAsset(false);
      }
    } finally {
      await Promise.all([loadAssets(), loadProject(id)]);
      setAddingAsset(false);
    }
  };

  // Callers that already hold the server's updated asset pass it in, and that one
  // row is patched in place rather than re-downloading every asset in the project
  // plus the project record. The search still re-runs when a query is active: a
  // tag change decides result-set membership under a query like `tag:Recheck` and
  // determines which spans highlight, so patching locally would leave the list
  // silently answering the operator's query with a stale set. That re-query is
  // scoped to the matching subset, so it stays far cheaper than the full reload.
  // Callers that can also reorder the list or shift the project's counters (the
  // edit form, the tag manager) omit the asset and take the full reload below.
  const handleAssetUpdated = async (updated?: Asset) => {
    if (!id) return;
    if (updated) {
      setAssets((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
      setDetailAsset((prev) => (prev && prev.id === updated.id ? withHighlights(prev, updated) : prev));
      if (query) search(query, id);
      return;
    }
    const [fresh] = await Promise.all([loadAssets(), loadProject(id)]);
    // Reseat the open panel on the freshly fetched row. When the asset is gone
    // the panel closes through closeDetail, so `?asset` leaves the URL with it
    // instead of lingering until the fallback fetch 404s it away.
    if (detailAsset) {
      const row = fresh.find((a) => a.id === detailAsset.id);
      if (row) setDetailAsset(withHighlights(detailAsset, row));
      else closeDetail();
    }
    // The table renders `results` while a query is active, and those are stale
    // the moment an asset changes — re-run the search so the rows follow.
    if (query) search(query, id);
  };

  const handleAssetDeleted = async () => {
    if (!id) return;
    closeDetail();
    await Promise.all([loadAssets(), loadProject(id)]);
  };

  if (!current) return <div style={{ color: 'var(--text-muted)' }}>Loading...</div>;

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'var(--bg-base)',
    border: '1px solid var(--border-default)',
    borderRadius: 6, color: 'var(--text-primary)', padding: '9px 12px', fontSize: 13,
    outline: 'none', fontFamily: 'var(--font-mono)',
    transition: 'border-color var(--transition-fast)',
  };

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {/* minWidth 0 lets this flex item shrink below its content's min-content
          width; without it the asset table widens the page instead. */}
      <div style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
        <ProjectHeader project={current} onRunRecon={() => setShowReconModal(true)} onEdit={() => setShowEdit(true)} />

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border-subtle)', marginBottom: 16 }}>
          {(['assets', 'screenshots', 'findings'] as ProjectTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => { setActiveTab(tab); if (tab !== 'assets') closeDetail(); }}
              style={{
                background: 'transparent', border: 'none',
                borderBottom: activeTab === tab ? '2px solid var(--accent-primary)' : '2px solid transparent',
                color: activeTab === tab ? 'var(--accent-primary)' : 'var(--text-muted)',
                padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                marginBottom: -1, transition: 'all var(--transition-fast)', textTransform: 'capitalize',
              }}
            >
              {tab}
            </button>
          ))}
        </div>

        {activeTab === 'findings' && id && (
          <FindingsSearchView projectId={id} />
        )}

        {activeTab === 'screenshots' && (
          <ScreenshotsView assets={assets} projectId={id!} onChanged={loadAssets} />
        )}

        {activeTab === 'assets' && (<>
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <SearchBar
              value={query}
              onChange={handleSearch}
              projectId={id}
              resultCount={query ? results.length : assets.length}
              loading={searchLoading}
            />
          </div>
          {isAdmin && (
            <button
              onClick={() => setShowTagManager(true)}
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
                border: '1px solid var(--border-default)',
                borderRadius: 6, padding: '7px 14px', fontSize: 12, fontWeight: 500, cursor: 'pointer',
                transition: 'all var(--transition-fast)',
              }}
            >
              <Tags size={13} /> Tags
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => { setShowAddAsset(!showAddAsset); setAddErrors([]); }}
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                background: showAddAsset ? 'var(--accent-subtle)' : 'var(--bg-elevated)',
                color: showAddAsset ? 'var(--accent-primary)' : 'var(--text-secondary)',
                border: showAddAsset ? '1px solid var(--accent-border)' : '1px solid var(--border-default)',
                borderRadius: 6, padding: '7px 14px', fontSize: 12, fontWeight: 500, cursor: 'pointer',
                transition: 'all var(--transition-fast)',
              }}
            >
              <Plus size={13} /> Add Asset
            </button>
          )}
        </div>

        {/* Add Asset inline form */}
        {showAddAsset && (
          <div style={{
            background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
            borderRadius: 8, padding: 16, marginBottom: 14,
            animation: 'fadeIn 150ms ease',
          }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div style={{ flex: 1 }}>
                <textarea
                  value={newAssetValue}
                  onChange={(e) => { setNewAssetValue(e.target.value); setAddErrors([]); }}
                  placeholder={"sub.example.com [200] [Page Title] [12345] [Next.js, PHP]\nanother.example.com"}
                  rows={3}
                  style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.6, fontSize: 12 }}
                />
              </div>
              <button
                onClick={handleAddAsset}
                disabled={addingAsset || !newAssetValue.trim()}
                style={{
                  background: 'var(--accent-primary)',
                  color: 'var(--bg-base)', border: '1px solid var(--accent-dim)',
                  borderRadius: 6, padding: '7px 14px', fontSize: 12, fontWeight: 600,
                  cursor: addingAsset ? 'not-allowed' : 'pointer',
                  opacity: addingAsset || !newAssetValue.trim() ? 0.45 : 1,
                  transition: 'all var(--transition-fast)',
                }}
              >
                {addingAsset ? 'Adding...' : 'Add'}
              </button>
            </div>
            {addErrors.length > 0 && (
              <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {addErrors.map((e, idx) => (
                  <div key={`${e.line}-${idx}`} style={{
                    display: 'flex', gap: 8, alignItems: 'flex-start',
                    background: 'var(--status-error-bg, rgba(255,0,0,0.08))',
                    border: '1px solid var(--status-error-border, rgba(255,0,0,0.28))',
                    borderRadius: 6, padding: '7px 10px',
                    fontSize: 11, fontFamily: 'var(--font-mono)', lineHeight: 1.5,
                  }}>
                    <span style={{ color: 'var(--text-code)', flexShrink: 0 }}>{e.line}</span>
                    <span style={{ color: 'var(--status-error)' }}>{e.detail}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <BulkActionsMenu
          selectedCount={selectedIds.size}
          onRunTech={() => runScan('tech')}
          onRunCrawl={() => runScan('crawl')}
          onClear={() => setSelectedIds(new Set())}
          onDeleteSelected={async () => {
            if (!id) return;
            for (const assetId of selectedIds) {
              await deleteAsset(id, assetId);
            }
            setSelectedIds(new Set());
            await Promise.all([loadAssets(), loadProject(id)]);
          }}
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 12 }}>
          <AssetTable
            assets={displayAssets}
            selectedIds={selectedIds}
            onToggleSelect={toggleSelect}
            onSelectAll={selectAll}
            onAssetClick={openDetail}
            focusAssetId={focusAssetId}
          />
          <TechPieChart assets={displayAssets} />
        </div>
        </>)}
      </div>

      {detailAsset && (
        <div
          onClick={closeDetail}
          style={{
            position: 'fixed', inset: 0, zIndex: 900,
            background: 'rgba(0,0,0,0.45)',
            display: 'flex', justifyContent: 'flex-end',
            animation: 'fadeIn 150ms ease',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ height: '100%', animation: 'slideInRight 180ms ease' }}
          >
            <AssetDetail
              asset={detailAsset}
              highlights={query ? (detailAsset as Partial<AssetSearchResult>).highlights : undefined}
              onClose={closeDetail}
              onAssetUpdated={handleAssetUpdated}
              onAssetDeleted={handleAssetDeleted}
            />
          </div>
        </div>
      )}

      {id && (
        <TagManager
          projectId={id}
          open={showTagManager}
          onClose={() => setShowTagManager(false)}
          // Wrapped, not passed by reference: a rename or delete here rewrites
          // many assets at once, so this must always take the full-refetch path
          // even if the dialog ever starts calling onChanged with an argument.
          onChanged={() => handleAssetUpdated()}
        />
      )}

      {current && (
        <ProjectEditOverlay
          project={current}
          open={showEdit}
          onClose={() => setShowEdit(false)}
          onUpdated={() => { if (id) loadProject(id); loadProjects(); }}
          onDeleted={() => { loadProjects(); navigate('/projects'); }}
        />
      )}

      {showReconModal && current && (
        <ReconScopeModal
          domains={current.root_domains}
          onConfirm={handleReconConfirm}
          onClose={() => setShowReconModal(false)}
        />
      )}
    </div>
  );
}
