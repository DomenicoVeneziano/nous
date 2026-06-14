// frontend/src/store/projectStore.ts
import { create } from 'zustand';
import type { Project } from '../types/project';
import { fetchProjects, fetchProject } from '../api/projects';

interface ProjectState {
  projects: Project[];
  current: Project | null;
  loading: boolean;
  loadProjects: () => Promise<void>;
  loadProject: (id: string) => Promise<void>;
  setCurrent: (p: Project | null) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  current: null,
  loading: false,

  loadProjects: async () => {
    set({ loading: true });
    try {
      const projects = await fetchProjects();
      set({ projects, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  loadProject: async (id: string) => {
    set({ loading: true });
    try {
      const project = await fetchProject(id);
      set({ current: project, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  setCurrent: (p) => set({ current: p }),
}));
