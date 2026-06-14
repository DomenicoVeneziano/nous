// frontend/src/pages/ProjectView.tsx
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { fetchAllAssets, createAsset, deleteAsset } from '../api/assets';
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
import { useSearch } from '../hooks/useSearch';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAuth } from '../hooks/useAuth';
import { Plus } from 'lucide-react';

type ProjectTab = 'assets' | 'screenshots' | 'findings';

const LINE_RE = /^(\S+)(?:\s+\[(\d+)\])?(?:\s+\[([^\]]+)\])?(?:\s+\[(\d+)\])?(?:\s+\[([^\]]+)\])?$/;

function parseLine(raw: string, assetType: 'subdomain' | 'ip'): AssetCreate {
  const trimmed = raw.trim();
  const match = trimmed.match(LINE_RE);
  if (!match) return { asset: trimmed, asset_type: assetType };
  const [, hostname, statusRaw, titleRaw, lengthRaw, techRaw] = match;
  const payload: AssetCreate = { asset: hostname, asset_type: assetType };
  if (statusRaw !== undefined) payload.status_code = parseInt(statusRaw, 10);
  if (titleRaw !== undefined) payload.title = titleRaw.trim();
  if (lengthRaw !== undefined) payload.content_length = parseInt(lengthRaw, 10);
  if (techRaw !== undefined) payload.technologies = techRaw.split(',').map((t) => t.trim()).filter(Boolean);
  return payload;
}

export default function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { current, loadProject, loadProjects } = useProjectStore();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [detailAsset, setDetailAsset] = useState<Asset | null>(null);
  const [showEdit, setShowEdit] = useState(false);
  const [showReconModal, setShowReconModal] = useState(false);
  const [showAddAsset, setShowAddAsset] = useState(false);
  const [newAssetValue, setNewAssetValue] = useState('');
  const [newAssetType, setNewAssetType] = useState<'subdomain' | 'ip'>('subdomain');
  const [addingAsset, setAddingAsset] = useState(false);
  const { results, loading: searchLoading, search, query } = useSearch();
  const assetUpdateTimer = useRef<ReturnType<typeof setTimeout>>();
  const { isAdmin } = useAuth();
  const [activeTab, setActiveTab] = useState<ProjectTab>('assets');

  const loadAssets = useCallback(async (): Promise<Asset[]> => {
    if (!id) return [];
    const data = await fetchAllAssets(id);
    setAssets(data);
    return data;
  }, [id]);

  useEffect(() => {
    if (id) {
      loadProject(id);
      loadAssets();
    }
  }, [id]);

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
      await Promise.allSettled(lines.map((line) => createAsset(id, parseLine(line, newAssetType))));
    } finally {
      await Promise.all([loadAssets(), loadProject(id)]);
      setNewAssetValue('');
      setShowAddAsset(false);
      setAddingAsset(false);
    }
  };

  const handleAssetUpdated = async () => {
    if (!id) return;
    const [updated] = await Promise.all([loadAssets(), loadProject(id)]);
    if (detailAsset) {
      setDetailAsset(updated.find((a) => a.id === detailAsset.id) ?? null);
    }
  };

  const handleAssetDeleted = async () => {
    if (!id) return;
    setDetailAsset(null);
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
      <div style={{ flex: 1, overflow: 'auto', paddingRight: detailAsset ? 0 : undefined }}>
        <ProjectHeader project={current} onRunRecon={() => setShowReconModal(true)} onEdit={() => setShowEdit(true)} />

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border-subtle)', marginBottom: 16 }}>
          {(['assets', 'screenshots', 'findings'] as ProjectTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => { setActiveTab(tab); if (tab !== 'assets') setDetailAsset(null); }}
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
          <div style={{ flex: 1 }}>
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
              onClick={() => setShowAddAsset(!showAddAsset)}
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
                  onChange={(e) => setNewAssetValue(e.target.value)}
                  placeholder={"sub.example.com [200] [Page Title] [12345] [Next.js, PHP]\nanother.example.com"}
                  rows={3}
                  style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.6, fontSize: 12 }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <select
                  value={newAssetType}
                  onChange={(e) => setNewAssetType(e.target.value as 'subdomain' | 'ip')}
                  style={{ ...inputStyle, width: 120, cursor: 'pointer', fontSize: 12 }}
                >
                  <option value="subdomain">Subdomain</option>
                  <option value="ip">IP</option>
                </select>
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
            </div>
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

        <div style={{ display: 'grid', gridTemplateColumns: detailAsset ? '1fr' : '1fr 300px', gap: 12 }}>
          <AssetTable
            assets={displayAssets}
            selectedIds={selectedIds}
            onToggleSelect={toggleSelect}
            onSelectAll={selectAll}
            onAssetClick={setDetailAsset}
          />
          {!detailAsset && <TechPieChart assets={displayAssets} />}
        </div>
        </>)}
      </div>

      {detailAsset && (
        <AssetDetail
          asset={detailAsset}
          highlights={query ? (detailAsset as AssetSearchResult).highlights : undefined}
          onClose={() => setDetailAsset(null)}
          onAssetUpdated={handleAssetUpdated}
          onAssetDeleted={handleAssetDeleted}
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
