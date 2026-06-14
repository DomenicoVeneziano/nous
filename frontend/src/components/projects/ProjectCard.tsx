// frontend/src/components/projects/ProjectCard.tsx
import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { Project } from '../../types/project';
import ProjectIcon from './ProjectIcon';

interface Props {
  project: Project;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: (id: string) => void;
}

function avatarColor(str: string): string {
  const greys = ['#f5f5f5', '#d4d4d4', '#a3a3a3', '#8a8a8a', '#737373', '#606060'];
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  return greys[Math.abs(hash) % greys.length];
}

export default function ProjectCard({ project, selectable, selected, onToggleSelect }: Props) {
  const navigate = useNavigate();
  const monogram = project.title.slice(0, 2).toUpperCase();
  const color = avatarColor(project.title);

  const handleClick = () => {
    if (selectable && onToggleSelect) {
      onToggleSelect(project.id);
    } else {
      navigate(`/projects/${project.id}`);
    }
  };

  const handleCheckbox = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggleSelect?.(project.id);
  };

  return (
    <div
      onClick={handleClick}
      style={{
        backgroundColor: selected ? 'var(--bg-selected)' : 'var(--bg-surface)',
        border: selected ? '1px solid var(--accent-border)' : '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: 18, cursor: 'pointer',
        transition: 'all var(--transition-base)',
        boxShadow: selected
          ? 'inset 0 0 0 1px rgba(255,255,255,0.10), var(--shadow-card)'
          : 'var(--shadow-card)',
        position: 'relative',
        overflow: 'hidden',
      }}
      onMouseEnter={(e) => {
        if (!selected) {
          e.currentTarget.style.borderColor = 'var(--border-emphasis)';
          e.currentTarget.style.boxShadow = 'var(--shadow-elevated)';
        }
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        if (!selected) {
          e.currentTarget.style.borderColor = 'var(--border-subtle)';
          e.currentTarget.style.boxShadow = selected
            ? 'inset 0 0 0 1px rgba(255,255,255,0.10), var(--shadow-card)'
            : 'var(--shadow-card)';
        }
        e.currentTarget.style.transform = 'translateY(0)';
      }}
    >
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 1,
        background: 'linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.08), transparent)',
      }} />

      {/* Selection checkbox */}
      {selectable && (
        <div
          onClick={handleCheckbox}
          style={{
            position: 'absolute', top: 10, right: 10, zIndex: 2,
            width: 18, height: 18, borderRadius: 'var(--radius-sm)',
            background: selected ? 'var(--accent-primary)' : 'var(--bg-base)',
            border: selected ? '1px solid var(--accent-primary)' : '1px solid var(--border-default)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', transition: 'all var(--transition-fast)',
          }}
        >
          {selected && (
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M2.5 6L5 8.5L9.5 3.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        {project.icon ? (
          <ProjectIcon
            projectId={project.id}
            alt={project.title}
            style={{
              width: 38, height: 38, borderRadius: '50%', objectFit: 'cover',
              border: '1px solid var(--border-default)',
            }}
          />
        ) : (
          <div style={{
            width: 38, height: 38, borderRadius: '50%',
            background: 'var(--bg-elevated)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 13, fontWeight: 600, color,
            border: '1px solid var(--border-default)',
            fontFamily: 'var(--font-mono)',
          }}>
            {monogram}
          </div>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: 'var(--text-primary)', fontSize: 14, fontWeight: 600 }}>{project.title}</div>
          {project.description && (
            <div style={{
              color: 'var(--text-muted)', fontSize: 12, marginTop: 2,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{project.description}</div>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 14, fontSize: 12, color: 'var(--text-secondary)' }}>
          <span>
            <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
              {project.asset_count}
            </strong> assets
          </span>
          <span>
            <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
              {project.tech_count}
            </strong> tech
          </span>
      </div>

      {project.last_scan_date && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10, fontFamily: 'var(--font-mono)' }}>
          Last scan: {new Date(project.last_scan_date).toLocaleDateString()}
        </div>
      )}
    </div>
  );
}
