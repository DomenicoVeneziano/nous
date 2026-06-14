# backend/routers/stats.py
import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from auth.middleware import require_viewer

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/technologies")
def tech_distribution(db: Session = Depends(get_db), _: dict = Depends(require_viewer)):
    """
    Return per-technology asset counts across all projects.
    Aggregates in Python to handle both raw-SQL-written (TEXT) and
    ORM-written (JSON-typed) rows without relying on SQLite's json_each.
    """
    rows = db.execute(text(
        "SELECT technologies FROM assets "
        "WHERE technologies IS NOT NULL AND technologies != '' AND technologies != '[]'"
    )).fetchall()

    counts: dict[str, int] = {}
    for (value,) in rows:
        # value may be a Python list (ORM path) or a JSON string (raw-SQL path)
        if isinstance(value, list):
            techs = value
        elif isinstance(value, str):
            try:
                techs = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                continue
        else:
            continue
        for tech in techs:
            if tech and isinstance(tech, str):
                counts[tech] = counts.get(tech, 0) + 1

    return sorted(
        [{"name": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )
