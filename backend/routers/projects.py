# backend/routers/projects.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from auth.middleware import require_admin, require_viewer
from schemas.project import ProjectCreate, ProjectUpdate, ProjectOut, BulkProjectAction
from services import project_service
from config import settings
from pathlib import Path

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_ICON_SIZE = 2 * 1024 * 1024  # 2MB

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    return project_service.list_projects(db)


@router.post("/", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    return project_service.create_project(db, data)


@router.post("/bulk-delete", status_code=200)
def bulk_delete_projects(data: BulkProjectAction, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    deleted = 0
    for pid in data.project_ids:
        if project_service.delete_project(db, pid):
            deleted += 1
    return {"deleted": deleted}


@router.post("/{project_id}/icon")
async def upload_icon(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, f"Invalid image type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}")
    content = await file.read()
    if len(content) > MAX_ICON_SIZE:
        raise HTTPException(400, "Image too large (max 2MB)")

    # Determine extension from content type
    ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
    ext = ext_map.get(file.content_type, ".png")

    project_dir = settings.DATA_DIR / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    # Remove old icon files
    for old in project_dir.glob("icon.*"):
        old.unlink()

    icon_path = project_dir / f"icon{ext}"
    icon_path.write_bytes(content)

    # Store relative icon path in DB
    project.icon = f"icon{ext}"
    db.commit()
    db.refresh(project)
    return {"icon": project.icon}


@router.delete("/{project_id}/icon", status_code=200)
def delete_icon(project_id: str, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project_dir = settings.DATA_DIR / "projects" / project_id
    for old in project_dir.glob("icon.*"):
        old.unlink()
    project.icon = None
    db.commit()
    return {"status": "ok"}


@router.get("/{project_id}/icon")
def get_icon(project_id: str, db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    project = project_service.get_project(db, project_id)
    if not project or not project.icon:
        raise HTTPException(404, "No icon")
    icon_path = (settings.DATA_DIR / "projects" / project_id / project.icon).resolve()
    safe_base = (settings.DATA_DIR / "projects" / project_id).resolve()
    if not icon_path.is_relative_to(safe_base) or not icon_path.is_file():
        raise HTTPException(404, "Icon not found")
    return FileResponse(icon_path, headers={"Content-Security-Policy": "default-src 'none'"})


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, data: ProjectUpdate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    project = project_service.update_project(db, project_id, data)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    if not project_service.delete_project(db, project_id):
        raise HTTPException(404, "Project not found")
