// frontend/src/pages/Dashboard.tsx
import React, { useEffect, useMemo, useState } from 'react';
import { useProjectStore } from '../store/projectStore';
import { useScanStore } from '../store/scanStore';
import StatsBar from '../components/dashboard/StatsBar';
import ProjectAssetChart from '../components/dashboard/ProjectAssetChart';
import TechHistogram from '../components/dashboard/TechHistogram';
import { fetchTechDistribution } from '../api/assets';

export default function Dashboard() {
  const { projects, loadProjects } = useProjectStore();
  const { queue, history, loadQueue, loadHistory } = useScanStore();
  const [techData, setTechData] = useState<{ name: string; count: number }[]>([]);

  useEffect(() => {
    loadProjects();
    loadQueue();
    loadHistory();
    fetchTechDistribution().then(setTechData).catch(() => {});
  }, []);

  const totalAssets = projects.reduce((s, p) => s + p.asset_count, 0);
  const totalTech = projects.reduce((s, p) => s + p.tech_count, 0);
  const runningJobs = queue.filter((j) => j.status === 'running').length;

  const stats = [
    { label: 'Projects', value: projects.length },
    { label: 'Total Assets', value: totalAssets },
    { label: 'Tech Identified', value: totalTech },
    { label: 'Running Jobs', value: runningJobs },
    { label: 'Queued Jobs', value: queue.filter((j) => j.status === 'queued').length },
    { label: 'Completed Scans', value: history.filter((j) => j.status === 'done').length },
  ];

  const assetDistribution = useMemo(() =>
    projects
      .filter(p => p.asset_count > 0)
      .map(p => ({ name: p.title, value: p.asset_count }))
      .sort((a, b) => b.value - a.value),
  [projects]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div>
        <h2 style={{ color: 'var(--text-primary)', fontSize: 20, fontWeight: 700, margin: '0 0 4px' }}>Dashboard</h2>
        <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: 0, fontFamily: 'var(--font-mono)' }}>
          Attack surface overview
        </p>
      </div>
      <StatsBar stats={stats} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <ProjectAssetChart data={assetDistribution} />
        <TechHistogram data={techData} />
      </div>
    </div>
  );
}
