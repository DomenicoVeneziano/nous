// frontend/src/pages/Data.tsx
import React, { useEffect, useRef, useState } from 'react';
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
  const { queue, history, scanLines, scanLineOffset, scanProgress, loadQueue, loadHistory, addScanLine, clearScanLines, setScanProgress } = useScanStore();
  const { projects, loadProjects } = useProjectStore();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  useEffect(() => {
    clearScanLines();
    loadQueue();
    loadHistory();
    loadProjects();
  }, []);

  const runningJob = queue.find((j) => j.status === 'running');
  const runningJobId = runningJob?.id ?? null;

  // Which job may drive the progress bar. `job_started` carries the id, so the
  // bar no longer waits on the async queue fetch: a scan whose whole first pass
  // finishes before `/scans/queue` returns still renders. Refs, so the socket
  // handlers always read the current value without re-subscribing.
  const startedJobIdRef = useRef<string | null>(null);
  // The queue's running job is the fallback authority when the page mounts in
  // the middle of a scan and no `job_started` was ever received here.
  const runningJobIdRef = useRef<string | null>(null);
  runningJobIdRef.current = runningJobId;

  const isWatchedJob = (jobId: string) =>
    jobId === startedJobIdRef.current ||
    (startedJobIdRef.current === null && jobId === runningJobIdRef.current);

  // A job reached a terminal state: stop letting it drive the bar and drop its
  // snapshot, so the label and fill do not linger at their final values.
  const finishJob = (data: Record<string, unknown>) => {
    const jobId = typeof data.job_id === 'string' ? data.job_id : startedJobIdRef.current;
    if (jobId !== null && jobId === startedJobIdRef.current) startedJobIdRef.current = null;
    const current = useScanStore.getState().scanProgress;
    if (current && (jobId === null || current.job_id === jobId)) setScanProgress(null);
    loadQueue();
    loadHistory();
  };

  useWebSocket({
    scan_line: (data) => addScanLine(data.line as string),
    scan_progress: (data) => {
      // The store keeps whatever it is handed, so the job filter lives here:
      // only the job the monitor is watching may drive the bar.
      if (typeof data.job_id !== 'string' || !isWatchedJob(data.job_id)) return;
      if (typeof data.scan_type !== 'string' || typeof data.pass_label !== 'string') return;
      const counts = ['pass_index', 'pass_total', 'assets_done', 'assets_total', 'pass_assets_done', 'pass_assets_total'];
      if (counts.some((k) => typeof data[k] !== 'number' || !Number.isFinite(data[k] as number))) return;
      setScanProgress({
        job_id: data.job_id,
        scan_type: data.scan_type,
        pass_label: data.pass_label,
        pass_index: data.pass_index as number,
        pass_total: data.pass_total as number,
        assets_done: data.assets_done as number,
        assets_total: data.assets_total as number,
        pass_assets_done: data.pass_assets_done as number,
        pass_assets_total: data.pass_assets_total as number,
      });
    },
    job_started: (data) => {
      if (typeof data.job_id === 'string') startedJobIdRef.current = data.job_id;
      loadQueue();
    },
    job_complete: (data) => { finishJob(data); },
    job_failed: (data) => { finishJob(data); },
    output_cleared: () => { clearScanLines(); },
  }, () => { loadQueue(); });

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
          progress={scanProgress}
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
