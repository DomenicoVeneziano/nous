# backend/routers/files.py
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, FileResponse
from pydantic import BaseModel
from pathlib import Path
from auth.middleware import require_viewer, require_admin
from storage import PROJECTS_DIR, resolve_within
import os

_ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


class FileWriteRequest(BaseModel):
    path: str
    content: str

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/image")
def get_image(
    path: str = Query(...),
    _: dict = Depends(require_viewer),
):
    """Serve a binary image (e.g. a tech-analysis screenshot) from data/projects/."""
    file_path = resolve_within(path)
    if file_path is None:
        raise HTTPException(403, "Access denied")
    if file_path.suffix.lower() not in _ALLOWED_IMAGE_EXT:
        raise HTTPException(400, "Not an image file")
    if not file_path.is_file():
        raise HTTPException(404, "File not found")

    return FileResponse(file_path)


@router.get("/tree")
def get_file_tree(
    project_id: str = Query(...),
    _: dict = Depends(require_viewer),
):
    """Return the directory structure for a project's data folder."""
    base = PROJECTS_DIR.resolve()
    # project_id is a raw query parameter: confine it like every other stored
    # path before walking it, or "../.." lists the whole app root (the
    # relative_to() below matches lexically and would not catch it). Landing on
    # the projects root itself ("" or ".") is an escape of the same kind.
    project_dir = resolve_within(project_id)
    if project_dir is None or project_dir == base:
        raise HTTPException(403, "Access denied")
    if not project_dir.is_dir():
        raise HTTPException(404, "Project directory not found")

    tree = []
    for root, dirs, files in os.walk(project_dir):
        rel_root = Path(root).relative_to(base)
        for f in sorted(files):
            tree.append(str(rel_root / f))
    return {"files": tree}


@router.get("/content")
def get_file_content(
    path: str = Query(...),
    _: dict = Depends(require_viewer),
):
    """Read file content within the data/projects/ directory."""
    file_path = resolve_within(path)
    if file_path is None:
        raise HTTPException(403, "Access denied")
    if not file_path.is_file():
        raise HTTPException(404, "File not found")

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise HTTPException(500, "Failed to read file")

    return PlainTextResponse(content)


@router.put("/content")
def update_file_content(
    data: FileWriteRequest,
    _: dict = Depends(require_admin),
):
    """Write file content within the data/projects/ directory. Admin only."""
    # No is_file() test here, unlike the read paths: this route creates the file
    # when it does not exist yet, so only its parent has to be a real directory.
    file_path = resolve_within(data.path)
    if file_path is None:
        raise HTTPException(403, "Access denied")
    if not file_path.parent.is_dir():
        raise HTTPException(404, "Parent directory not found")

    try:
        file_path.write_text(data.content, encoding="utf-8")
    except OSError:
        raise HTTPException(500, "Failed to write file")

    return {"status": "ok", "path": data.path}
