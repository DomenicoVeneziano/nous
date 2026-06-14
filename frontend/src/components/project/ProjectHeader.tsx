// frontend/src/components/project/ProjectHeader.tsx
import React from 'react';
import type { Project } from '../../types/project';
import { Pencil } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import ProjectIcon from '../projects/ProjectIcon';

interface Props {
  project: Project;
  onRunRecon: () => void;
  onEdit?: () => void;
}

export default function ProjectHeader({ project, onRunRecon, onEdit }: Props) {
  const { isAdmin } = useAuth();

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      marginBottom: 24,
    }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {project.icon && (
            <ProjectIcon
              projectId={project.id}
              alt={project.title}
              style={{ width: 32, height: 32, borderRadius: 6, objectFit: 'cover' }}
            />
          )}
          <h2 style={{ color: 'var(--text-primary)', fontSize: 18, fontWeight: 600, margin: 0 }}>{project.title}</h2>
          {isAdmin && onEdit && (
            <button
              onClick={onEdit}
              className="btn-secondary"
              style={{ padding: '4px 8px', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}
            >
              <Pencil size={11} /> Edit
            </button>
          )}
        </div>
        {project.description && (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 5 }}>{project.description}</div>
        )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
          {project.root_domains.map((d) => (
            <span key={d} style={{
              background: 'var(--bg-elevated)', color: 'var(--text-code)',
              border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)',
              padding: '2px 8px', fontSize: 11, fontFamily: 'var(--font-mono)',
            }}>{d}</span>
          ))}
          <span style={{ fontSize: 12, color: 'var(--text-secondary)', alignSelf: 'center' }}>
            <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{project.asset_count}</strong> assets
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)', alignSelf: 'center' }}>
            <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{project.tech_count}</strong> tech
          </span>
        </div>
      </div>
      <button onClick={onRunRecon} className="btn-primary" style={{ padding: '9px 20px', fontSize: 13 }}>
        Run Recon
      </button>
    </div>
  );
}
