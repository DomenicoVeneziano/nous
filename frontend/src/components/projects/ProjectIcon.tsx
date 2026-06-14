// frontend/src/components/projects/ProjectIcon.tsx
import React, { useEffect, useState } from 'react';
import { fetchProjectIconUrl } from '../../api/projects';

interface Props {
  projectId: string;
  alt: string;
  style: React.CSSProperties;
}

/**
 * Loads a project icon as an authenticated blob and renders it, managing the
 * object-URL lifecycle (revoked on unmount / id change to avoid leaks). The
 * icon endpoint requires auth, so a plain <img src> would 401.
 */
export default function ProjectIcon({ projectId, alt, style }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    fetchProjectIconUrl(projectId)
      .then((u) => {
        if (active) {
          objectUrl = u;
          setUrl(u);
        } else {
          URL.revokeObjectURL(u);
        }
      })
      .catch(() => { if (active) setFailed(true); });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [projectId]);

  if (failed || !url) {
    // Neutral placeholder keeps layout stable while loading or on error.
    return <div style={{ ...style, background: 'var(--bg-elevated)' }} />;
  }

  return <img src={url} alt={alt} style={style} />;
}
