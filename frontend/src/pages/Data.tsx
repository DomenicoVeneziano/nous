// frontend/src/pages/Data.tsx
import React, { useEffect, useState } from 'react';
import { useScanStore } from '../store/scanStore';
import { useProjectStore } from '../store/projectStore';
import { useWebSocket } from '../hooks/useWebSocket';
import ScanQueue from '../components/data/ScanQueue';
import ScanMonitor from '../components/data/ScanMonitor';
import ScanHistory from '../components/data/ScanHistory';
import FileExplorer from '../components/data/FileExplorer';

export default function Data() {
  const { queue, history, scanLines, loadQueue, loadHistory, addScanLine, clearScanLines } = useScanStore();
  const { projects, loadProjects } = useProjectStore();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  useEffect(() => {
    clearScanLines();
    loadQueue();
    loadHistory();
    loadProjects();
  }, []);

  useWebSocket({
    scan_line: (data) => addScanLine(data.line as string),
    job_started: () => { loadQueue(); },
    job_complete: () => { loadQueue(); loadHistory(); },
    job_failed: () => { loadQueue(); loadHistory(); },
    output_cleared: () => { clearScanLines(); },
  }, () => { loadQueue(); });

  const runningJob = queue.find((j) => j.status === 'running');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 14 }}>
        <ScanQueue jobs={queue} onRefresh={loadQueue} />
        <ScanMonitor
          lines={scanLines}
          activeJob={runningJob ? { scan_type: runningJob.scan_type, id: runningJob.id } : null}
        />
      </div>

      <ScanHistory jobs={history} onRefresh={loadHistory} />

      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)',
        borderRadius: 8, padding: 16, boxShadow: 'var(--shadow-card)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
          <span style={{
            fontSize: 13, fontWeight: 600, color: 'var(--text-primary)',
          }}>File Explorer</span>
          <select
            value={selectedProjectId || ''}
            onChange={(e) => setSelectedProjectId(e.target.value || null)}
            style={{
              background: 'var(--bg-elevated)', border: '1px solid var(--border-default)',
              borderRadius: 6, color: 'var(--text-primary)', padding: '5px 10px', fontSize: 12,
              outline: 'none', fontFamily: 'var(--font-mono)',
              transition: 'border-color var(--transition-fast)',
            }}
          >
            <option value="">Select Project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.title}</option>
            ))}
          </select>
        </div>
        <FileExplorer projectId={selectedProjectId} />
      </div>
    </div>
  );
}
