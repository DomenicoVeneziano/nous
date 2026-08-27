// frontend/src/components/projects/ScheduleFields.tsx
import React from 'react';
import type { ScanPhase, ScheduleUnit } from '../../types/project';
import { Repeat } from 'lucide-react';

export interface ScheduleValue {
  enabled: boolean;
  intervalValue: number;
  intervalUnit: ScheduleUnit;
  phases: ScanPhase[];
}

interface Props extends ScheduleValue {
  onChange: (value: ScheduleValue) => void;
}

const UNITS: ScheduleUnit[] = ['hours', 'days', 'weeks', 'months'];

const PHASES: { id: ScanPhase; label: string }[] = [
  { id: 'recon', label: 'Recon' },
  { id: 'tech', label: 'Tech' },
  { id: 'crawl', label: 'Crawl' },
];

// Same bounds the server puts on schedule_interval_value (ge=1, le=1000).
const MIN_INTERVAL = 1;
const MAX_INTERVAL = 1000;

/**
 * Mirrors the server's own rule: an enabled schedule without an interval in
 * range or without at least one phase is rejected with a 422, so Save stays
 * disabled rather than letting the overlay round-trip an error.
 */
export function isScheduleValid(value: ScheduleValue): boolean {
  if (!value.enabled) return true;
  return (
    Number.isFinite(value.intervalValue) &&
    value.intervalValue >= MIN_INTERVAL &&
    value.intervalValue <= MAX_INTERVAL &&
    UNITS.includes(value.intervalUnit) &&
    value.phases.length > 0
  );
}

export default function ScheduleFields({ enabled, intervalValue, intervalUnit, phases, onChange }: Props) {
  const emit = (patch: Partial<ScheduleValue>) =>
    onChange({ enabled, intervalValue, intervalUnit, phases, ...patch });

  const togglePhase = (id: ScanPhase) => {
    // Keep the display order stable regardless of the click order.
    const next = phases.includes(id)
      ? phases.filter((p) => p !== id)
      : PHASES.map((p) => p.id).filter((p) => p === id || phases.includes(p));
    emit({ phases: next });
  };

  const controlStyle: React.CSSProperties = {
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-md)', color: 'var(--text-primary)',
    padding: '7px 10px', fontSize: 13, outline: 'none',
    transition: 'border-color var(--transition-fast)',
  };

  // A cleared field reads as NaN and is left alone: it is a step on the way to
  // a new number, not a value the operator typed wrong.
  const intervalOutOfRange =
    Number.isFinite(intervalValue) && (intervalValue < MIN_INTERVAL || intervalValue > MAX_INTERVAL);

  return (
    <div>
      <label style={{
        display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
        fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)',
      }}>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => emit({ enabled: e.target.checked })}
          style={{ accentColor: 'var(--accent-primary)', cursor: 'pointer', margin: 0 }}
        />
        <Repeat size={12} />
        Rescan automatically
      </label>

      {enabled && (
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Every</span>
              <input
                type="number"
                min={MIN_INTERVAL}
                max={MAX_INTERVAL}
                // Clearing the field is a legitimate step on the way to a new
                // number: the empty string keeps the input controlled while the
                // NaN it stands for holds Save disabled until a digit arrives.
                value={Number.isFinite(intervalValue) ? intervalValue : ''}
                onChange={(e) => emit({ intervalValue: parseInt(e.target.value, 10) })}
                style={{ ...controlStyle, width: 72, fontFamily: 'var(--font-mono)' }}
              />
              <select
                value={intervalUnit}
                onChange={(e) => emit({ intervalUnit: e.target.value as ScheduleUnit })}
                style={{ ...controlStyle, cursor: 'pointer' }}
              >
                {UNITS.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </div>
            {intervalOutOfRange && (
              <div style={{ fontSize: 11, color: 'var(--status-error)', marginTop: 6 }}>
                Interval must be between {MIN_INTERVAL} and {MAX_INTERVAL}
              </div>
            )}
          </div>

          <div>
            <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>
              Phases
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {PHASES.map(({ id, label }) => {
                const on = phases.includes(id);
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => togglePhase(id)}
                    style={{
                      background: on ? 'var(--accent-subtle)' : 'var(--bg-elevated)',
                      color: on ? 'var(--text-primary)' : 'var(--text-muted)',
                      border: `1px solid ${on ? 'var(--accent-border)' : 'var(--border-subtle)'}`,
                      borderRadius: 'var(--radius-sm)',
                      padding: '2px 8px', fontSize: 11, fontFamily: 'var(--font-mono)',
                      cursor: 'pointer', transition: 'all var(--transition-fast)',
                    }}
                  >{label}</button>
                );
              })}
            </div>
            {phases.length === 0 && (
              <div style={{ fontSize: 11, color: 'var(--status-error)', marginTop: 6 }}>
                Select at least one phase
              </div>
            )}
          </div>

          <div style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }}>
            A cycle whose scan is still running when the next one is due is skipped, never queued twice.
          </div>
        </div>
      )}
    </div>
  );
}
