# backend/storage.py
"""Path confinement for everything the API reads or writes under data/projects/.

Every stored path (a screenshot, a response body, a project icon, a file the
file browser edits) arrives as a client- or scan-supplied relative string, so
each use has to prove it stays inside its base directory before touching disk.
"""
from pathlib import Path

from config import settings

# The loose base: files.py and the asset routes address paths that already carry
# their project id, so they are confined to the shared projects root. A route
# that already knows the project — the icon route — passes a tighter base.
PROJECTS_DIR = settings.DATA_DIR / "projects"


def validate_path_within(path: Path, base: Path) -> bool:
    """Ensure a path stays within the base directory."""
    try:
        return path.resolve().is_relative_to(base.resolve())
    except (OSError, ValueError):
        return False


def resolve_within(rel_path: str | Path, base: Path | None = None) -> Path | None:
    """Resolve `rel_path` under `base` (default: data/projects/), or None if it escapes.

    Resolution happens before the containment test, and both halves matter:
    `base / "/etc/passwd"` discards `base` entirely, and `base / "../../etc"`
    only reveals itself as an escape once the '..' segments are collapsed.

    Existence is deliberately not checked here — the read paths want a 404 for a
    missing file while the write path only needs its parent directory — so
    callers make that decision on the returned path themselves.
    """
    base = PROJECTS_DIR if base is None else base
    target = (base / rel_path).resolve()
    return target if validate_path_within(target, base) else None
