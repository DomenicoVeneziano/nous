// frontend/src/pages/Data.tsx
import React, { useEffect, useState } from 'react';
import { useScanStore } from '../store/scanStore';
import { useProjectStore } from '../store/projectStore';
import { useWebSocket } from '../hooks/useWebSocket';
import ScanQueue from '../components/data/ScanQueue';
import ScanMonitor from '../components/data/ScanMonitor';
import ScanHistory from '../components/data/ScanHistory';
import FileExplorer from '../components/data/FileExplorer';

// The queue/monitor grid row is what bounds both cards. `fit-content()` lets the
// row grow with whichever card is taller — a longer queue, a few lines of output —
// but never past this cap, which hands both children a definite height so their
// internal `overflow:auto` panes actually scroll instead of growing the page.
// A plain `auto` row (or a `min-content` minimum) is sized by the terminal's own
// content, so a full 1000-line buffer would stretch the row to ~22,000px, defeat
// the pane's scrolling, and push Scan History far down the page.
const MONITOR_ROW_MAX_HEIGHT = 520;

export default function Data() {
  const { queue, history, scanLines, scanLineOffset, loadQueue, loadHistory, addScanLine, clearScanLines } = useScanStore();
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
      <div style={{
        display: 'grid', gridTemplateColumns: '300px 1fr',
        gridTemplateRows: `fit-content(${MONITOR_ROW_MAX_HEIGHT}px)`,
        gap: 14,
      }}>
        <ScanQueue jobs={queue} onRefresh={loadQueue} />
        <ScanMonitor
          lines={scanLines}
          lineOffset={scanLineOffset}
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
