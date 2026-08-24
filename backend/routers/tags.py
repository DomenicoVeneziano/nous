# backend/routers/tags.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.middleware import require_admin, require_viewer
from database import get_db
from models.tag import Tag
from schemas.asset import AssetOut
from schemas.tag import TagAssign, TagCreate, TagOut, TagUpdate, TagWithCount
from services import asset_service, project_service, tag_service
from services.tag_service import TagError

router = APIRouter(prefix="/projects/{project_id}", tags=["tags"])


def _require_project(db: Session, project_id: str):
    """404 on an unknown project before anything else, so a caller cannot probe
    for tag ids belonging to a project they didn't name."""
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _require_tag(db: Session, project_id: str, tag_id: str) -> Tag:
    """Resolve a tag *within* the named project. Looking it up by id alone would
    let a tag from another project be edited through this project's URL."""
    tag = tag_service.get_tag(db, project_id, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    return tag


def _reject_system(tag: Tag) -> None:
    """System tags record how an asset was discovered. They are read-only over
    the API — enforced here, not merely hidden in the UI."""
    if tag.is_system:
        raise HTTPException(403, f"'{tag.name}' is a system tag and cannot be modified")


def _require_asset(db: Session, project_id: str, asset_id: str):
    asset = asset_service.get_asset(db, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Asset not found")
    return asset


def _asset_response(db: Session, asset) -> AssetOut:
    db.refresh(asset)
    tag_service.decorate_assets(db, [asset])
    return AssetOut.model_validate(asset)


@router.get("/tags", response_model=list[TagWithCount])
def list_tags(project_id: str, db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    _require_project(db, project_id)
    counts = tag_service.tag_asset_counts(db, project_id)
    return [
        TagWithCount(
            id=t.id, project_id=t.project_id, name=t.name, color=t.color,
            is_system=t.is_system, asset_count=counts.get(t.id, 0),
        )
        for t in tag_service.list_tags(db, project_id)
    ]


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(project_id: str, data: TagCreate, db: Session = Depends(get_db),
               _: dict = Depends(require_admin)):
    _require_project(db, project_id)
    try:
        name = tag_service.normalize_name(data.name)
        color = tag_service.normalize_color(data.color)
    except TagError as exc:
        raise HTTPException(422, str(exc))
    if tag_service.get_tag_by_name(db, project_id, name):
        raise HTTPException(409, f"Tag '{name}' already exists in this project")
    try:
        return tag_service.create_tag(db, project_id, name, color)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Tag '{name}' already exists in this project")


@router.put("/tags/{tag_id}", response_model=TagOut)
def update_tag(project_id: str, tag_id: str, data: TagUpdate,
               db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    _require_project(db, project_id)
    tag = _require_tag(db, project_id, tag_id)
    _reject_system(tag)

    name = None
    if data.name is not None:
        try:
            name = tag_service.normalize_name(data.name)
        except TagError as exc:
            raise HTTPException(422, str(exc))
        clash = tag_service.get_tag_by_name(db, project_id, name)
        if clash and clash.id != tag.id:
            raise HTTPException(409, f"Tag '{name}' already exists in this project")

    color_set = "color" in data.model_fields_set
    color = None
    if color_set:
        try:
            color = tag_service.normalize_color(data.color)
        except TagError as exc:
            raise HTTPException(422, str(exc))

    try:
        return tag_service.update_tag(db, tag, name, color, color_set)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Tag name already exists in this project")


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(project_id: str, tag_id: str, db: Session = Depends(get_db),
               _: dict = Depends(require_admin)):
    _require_project(db, project_id)
    tag = _require_tag(db, project_id, tag_id)
    _reject_system(tag)
    tag_service.delete_tag(db, tag)


@router.post("/assets/{asset_id}/tags", response_model=AssetOut)
def attach_tag(project_id: str, asset_id: str, data: TagAssign,
               db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """Attach a tag to an asset by id, or by name to create-and-attach in one
    call — which is what the tag entry field in the asset panel uses."""
    _require_project(db, project_id)
    asset = _require_asset(db, project_id, asset_id)

    if data.tag_id:
        tag = _require_tag(db, project_id, data.tag_id)
        _reject_system(tag)
    elif data.name is not None:
        # Answer the discovery-source name before normalize_name does: it
        # rejects those names as a generic "reserved" 422, which would otherwise
        # pre-empt the specific 403 for every system tag the project has not
        # materialised yet. Matching is by name, not by row, so the answer does
        # not depend on whether the engine has created the tag here.
        reserved = tag_service.system_tag_name(data.name)
        if reserved:
            raise HTTPException(
                403, f"'{reserved}' is a system tag and cannot be modified"
            )
        try:
            name = tag_service.normalize_name(data.name)
            color = tag_service.normalize_color(data.color)
        except TagError as exc:
            raise HTTPException(422, str(exc))
        tag = tag_service.get_tag_by_name(db, project_id, name)
        if tag:
            # Reachable only for an is_system row whose name is not one of the
            # source constants; the check above covers every name that is.
            _reject_system(tag)
        else:
            try:
                tag = tag_service.create_tag(db, project_id, name, color)
            except IntegrityError:
                db.rollback()
                tag = tag_service.get_tag_by_name(db, project_id, name)
                if not tag:
                    raise HTTPException(409, f"Tag '{name}' could not be created")
    else:
        raise HTTPException(422, "Provide either tag_id or name")

    tag_service.assign_tag(db, asset.id, tag.id)
    return _asset_response(db, asset)


@router.delete("/assets/{asset_id}/tags/{tag_id}", response_model=AssetOut)
def detach_tag(project_id: str, asset_id: str, tag_id: str,
               db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    _require_project(db, project_id)
    asset = _require_asset(db, project_id, asset_id)
    tag = _require_tag(db, project_id, tag_id)
    _reject_system(tag)
    tag_service.unassign_tag(db, asset.id, tag.id)
    return _asset_response(db, asset)
