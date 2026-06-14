// frontend/src/store/scanStore.ts
import { create } from 'zustand';
import type { ScanJob } from '../types/scan';
import { fetchQueue, fetchHistory } from '../api/scans';

interface ScanState {
  queue: ScanJob[];
  history: ScanJob[];
  scanLines: string[];
  loading: boolean;
  loadQueue: () => Promise<void>;
  loadHistory: () => Promise<void>;
  addScanLine: (line: string) => void;
  clearScanLines: () => void;
  updateJob: (job: Partial<ScanJob> & { id: string }) => void;
}

export const useScanStore = create<ScanState>((set) => ({
  queue: [],
  history: [],
  scanLines: [],
  loading: false,

  loadQueue: async () => {
    set({ loading: true });
    try {
      const queue = await fetchQueue();
      set({ queue, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  loadHistory: async () => {
    set({ loading: true });
    try {
      const history = await fetchHistory();
      set({ history, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  addScanLine: (line) =>
    set((state) => {
      // Deduplicate: skip if identical to the last line
      const last = state.scanLines[state.scanLines.length - 1];
      if (last === line) return state;
      return { scanLines: [...state.scanLines.slice(-999), line] };
    }),

  clearScanLines: () => set({ scanLines: [] }),

  updateJob: (job) =>
    set((state) => ({
      queue: state.queue.map((j) => (j.id === job.id ? { ...j, ...job } : j)),
    })),
}));
