// frontend/src/components/projects/ProjectGrid.tsx
import React from 'react';
import type { Project } from '../../types/project';
import ProjectCard from './ProjectCard';

interface Props {
  projects: Project[];
  selectable?: boolean;
  selectedIds?: Set<string>;
  onToggleSelect?: (id: string) => void;
}

export default function ProjectGrid({ projects, selectable, selectedIds, onToggleSelect }: Props) {
  if (projects.length === 0) {
    return (
      <div style={{
        textAlign: 'center', padding: 56, color: '#484848',
        fontSize: 13, fontFamily: 'var(--font-mono)',
      }}>
        No projects yet. Create one to get started.
      </div>
    );
  }

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
      gap: 14,
    }}>
      {projects.map((p) => (
        <ProjectCard
          key={p.id}
          project={p}
          selectable={selectable}
          selected={selectedIds?.has(p.id)}
          onToggleSelect={onToggleSelect}
        />
      ))}
    </div>
  );
}
