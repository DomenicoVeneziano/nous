// frontend/src/components/project/ProjectHeader.tsx
import React from 'react';
import type { Project } from '../../types/project';
import { CalendarClock, Pencil } from 'lucide-react';
import { parseBackendDate, formatDateTime } from '../../lib/datetime';
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
    <div style={{ marginBottom: 24 }}>
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
      {/* Run Recon shares the metadata row so its top edge lands with the chips rather than
          floating against the middle of the whole header, and it stays pinned right: the
          chip wrapper takes the slack, so the button sits in one place on every project. */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginTop: 10 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', flex: 1, minWidth: 0 }}>
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
          {/* The schedule reads as one item here, so an unscheduled project says so
              outright instead of leaving the row silent and the state hidden in Edit. */}
          {project.schedule_enabled ? (
            project.next_scan_at ? (
              <span style={{
                fontSize: 12, color: 'var(--text-secondary)', alignSelf: 'center',
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                <CalendarClock size={11} /> Next scan:{' '}
                <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                  {formatDateTime(parseBackendDate(project.next_scan_at))}
                </strong>
              </span>
            ) : project.schedule_cycle_active ? (
              /* next_scan_at is withheld while a cycle runs, so this state stands in for it. */
              <span style={{
                fontSize: 12, color: 'var(--accent-primary)', alignSelf: 'center',
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                <CalendarClock size={11} /> Scheduled scan in progress
              </span>
            ) : null
          ) : (
            <span style={{
              fontSize: 12, color: 'var(--text-muted)', alignSelf: 'center',
              display: 'flex', alignItems: 'center', gap: 4,
            }}>
              <CalendarClock size={11} /> No schedule
              {/* Only an admin can open Edit, so a viewer gets the state without a dead control. */}
              {isAdmin && onEdit && (
                <>
                  ·
                  <button
                    onClick={onEdit}
                    style={{
                      background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
                      fontSize: 12, fontFamily: 'inherit', color: 'var(--text-secondary)',
                      textDecoration: 'underline dotted',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--accent-primary)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-secondary)'; }}
                  >
                    set one
                  </button>
                </>
              )}
            </span>
          )}
        </div>
        <button
          onClick={onRunRecon}
          className="btn-primary"
          style={{ padding: '9px 20px', fontSize: 13, flexShrink: 0 }}
        >
          Run Recon
        </button>
      </div>
    </div>
  );
}
