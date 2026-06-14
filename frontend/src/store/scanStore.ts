// frontend/src/store/scanStore.ts
import { create } from 'zustand';
import type { ScanJob } from '../types/scan';
import { fetchQueue, fetchHistory } from '../api/scans';

const MAX_SCAN_LINES = 1000;

interface ScanState {
  queue: ScanJob[];
  history: ScanJob[];
  scanLines: string[];
  // Absolute index of scanLines[0] within the full stream. Climbs as the ring
  // buffer drops old lines, so line numbers and React keys stay stable.
  scanLineOffset: number;
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
  scanLineOffset: 0,
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
      const next = [...state.scanLines, line];
      // Cap the buffer; track how many lines were dropped off the front so
      // absolute line numbers and React keys remain stable across the slide.
      if (next.length > MAX_SCAN_LINES) {
        const dropped = next.length - MAX_SCAN_LINES;
        return {
          scanLines: next.slice(dropped),
          scanLineOffset: state.scanLineOffset + dropped,
        };
      }
      return { scanLines: next };
    }),

  clearScanLines: () => set({ scanLines: [], scanLineOffset: 0 }),

  updateJob: (job) =>
    set((state) => ({
      queue: state.queue.map((j) => (j.id === job.id ? { ...j, ...job } : j)),
    })),
}));
