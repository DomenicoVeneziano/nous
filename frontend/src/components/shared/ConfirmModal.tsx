// frontend/src/components/shared/ConfirmModal.tsx
import React, { useEffect } from 'react';

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** Card width cap. Overlays carry different content widths; 420 suits a
   *  confirmation prompt, forms want more. */
  maxWidth?: number;
}

/**
 * Backdrop + centred card shared by every overlay in the app.
 *
 * Escape and a click on the backdrop both route to `onClose`; clicks inside the
 * card never do. The key listener is bound only while the modal is open, so a
 * closed modal holds nothing.
 */
export function Modal({ open, title, onClose, children, footer, maxWidth = 420 }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-xl)',
        maxWidth, width: '90%',
        boxShadow: 'var(--shadow-elevated)',
        animation: 'fadeIn 150ms ease',
        // The backdrop is fixed and does not scroll, so a card taller than the
        // viewport would put its footer out of reach. Capping the height keeps
        // the card on screen; as a column it still sizes to its content.
        display: 'flex', flexDirection: 'column', maxHeight: 'calc(100vh - 48px)',
        overflow: 'hidden',
      }}>
        <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border-subtle)' }}>
          <h3 style={{ color: 'var(--text-primary)', fontSize: 15, fontWeight: 600, margin: 0 }}>{title}</h3>
        </div>
        {/* minHeight 0 is what makes the card's height cap bite: a flex child
            refuses to shrink below its content height without it, and tall
            content would push the footer past the card's clipped edge. */}
        <div style={{
          padding: '16px 22px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6,
          overflowY: 'auto', minHeight: 0,
        }}>{children}</div>
        {footer && (
          <div style={{
            padding: '14px 22px', borderTop: '1px solid var(--border-subtle)',
            display: 'flex', justifyContent: 'flex-end', gap: 8,
          }}>{footer}</div>
        )}
      </div>
    </div>
  );
}

interface Props {
  open: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  destructive?: boolean;
}

export default function ConfirmModal({ open, title, message, onConfirm, onCancel, destructive }: Props) {
  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button onClick={onCancel} className="btn-secondary">Cancel</button>
          <button onClick={onConfirm} className={destructive ? 'btn-danger' : 'btn-primary'}>Confirm</button>
        </>
      }
    >
      {message}
    </Modal>
  );
}
