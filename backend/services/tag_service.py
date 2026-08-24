# backend/services/tag_service.py
"""Tag storage, validation, and the derived "New!" marker.

Two kinds of tag share one table, separated by `is_system`:

  * system tags  — written by the engine, not by the operator. Most record how
    an asset was discovered (Passive, Bruteforce, Permutations, Crawling,
    Redirect, Manual, Seed); those accumulate and are never auto-removed, since
    provenance is an observation, not a curated label. "Proxied" instead records
    the vantage point of the stored result and is removed automatically when a
    later direct pass succeeds. The API rejects operator edits to all of them.
  * user tags    — free-form triage labels under full operator CRUD.

"New!" is in neither group. It is derived per request from
assets.first_seen_scan_id, so launching a recon job re-points it atomically and
a cancelled run cannot leave a half-wiped state behind.
"""
import re

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from models.asset import Asset
from models.tag import Tag, DERIVED_NEW_TAG, SYSTEM_TAG_NAMES

MAX_TAG_NAME_LENGTH = 40

# Printable label characters only. Excludes the quote/paren/bracket characters
# that carry meaning in the search query grammar, so `tag:<name>` stays parseable.
_NAME_RE = re.compile(r"^[A-Za-z0-9 ._\-+#/!]+$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_SYSTEM_NAMES_BY_FOLD = {n.casefold(): n for n in SYSTEM_TAG_NAMES}

# Rewrite the denormalized tags_text mirror on `assets`. The FTS triggers fire on
# `assets` only, so a write to the asset_tags join table would never reindex the
# row — routing every tag change through an UPDATE here is what keeps `tag:`
# searchable. Callers scope it with an id filter; see sync_tags_text.
#
# Byte-identical to the expression in engine/queue_manager.py: both processes
# write this column and identical SQL is what stops them ping-ponging two
# renderings of the same tag set at each other. Change one only by changing the other.
_TAGS_TEXT_EXPR = (
    "COALESCE(("
    " SELECT GROUP_CONCAT(t.name, ' ') FROM asset_tags at"
    " JOIN tags t ON t.id = at.tag_id WHERE at.asset_id = assets.id"
    "), '')"
)
_SYNC_TAGS_TEXT_SQL = f"UPDATE assets SET tags_text = {_TAGS_TEXT_EXPR}"

# Restrict the rewrite to rows whose mirror does not already hold what the SET
# would write. Every UPDATE on `assets` fires assets_au, which deletes and
# reinserts the entire FTS row, so an id-scoped rewrite with no value comparison
# pays full reindex cost for assets whose tags did not change. No call site here
# is known to pass unchanged ids — they all come from a rename, a delete or an
# assignment that genuinely moved — so this is carried for symmetry with the
# engine's copy, which does get handed whole result sets, not to fix a hot path.
#
# `IS NOT`, never `!=`: SQLite evaluates `NULL != x` to NULL, so `!=` would drop a
# NULL mirror from the update set and leave that row's drift unrepaired. tags_text
# is NOT NULL on every path today, so this guards a future nullable column rather
# than a reachable bug — but `!=` has no upside to trade for that.
#
# The subquery is spelled out on both sides on purpose — SET and WHERE have to
# evaluate the identical expression. GROUP_CONCAT's order is plan-determined
# (neither alphabetical nor insertion order), which is harmless precisely because
# both sides are the same subquery inside one statement, so a skip can only mean
# stored == computed. Do not add ORDER BY to one side alone.
#
# One incidental effect is lost: the unconditional form also rewrote the other
# eight FTS columns, so it repaired rows that had gone stale for reasons having
# nothing to do with tags. Repairing those is the job of the index rebuild in
# backend/database.py, which reruns the mirror unguarded behind its own sentinel.
_DRIFTED_ONLY = f"tags_text IS NOT {_TAGS_TEXT_EXPR}"


class TagError(ValueError):
    """Invalid tag input — routers map this to a 422."""


def _collapse(raw: str) -> str:
    """Trim and collapse internal runs of whitespace."""
    return " ".join((raw or "").split())


def system_tag_name(raw: str) -> str | None:
    """The canonical system tag name matching `raw`, or None.

    The single source of truth for "is this a system tag name". normalize_name
    rejects these as a 422, and the attach route consults it first to answer the
    more specific 403 — reading the same set from one place is what keeps the two
    from disagreeing about a name that differs only in case or spacing.
    """
    return _SYSTEM_NAMES_BY_FOLD.get(_collapse(raw).casefold())


def normalize_name(raw: str) -> str:
    """Validate and canonicalize a tag name, or raise TagError."""
    name = _collapse(raw)
    if not name:
        raise TagError("Tag name is required")
    if len(name) > MAX_TAG_NAME_LENGTH:
        raise TagError(f"Tag name must be at most {MAX_TAG_NAME_LENGTH} characters")
    if not _NAME_RE.match(name):
        raise TagError(
            "Tag name may only contain letters, digits, spaces and . _ - + # / !"
        )
    if name.casefold() == DERIVED_NEW_TAG.casefold():
        raise TagError(f"'{DERIVED_NEW_TAG}' is reserved and applied automatically")
    if system_tag_name(name):
        raise TagError(f"'{name}' is reserved for system tags")
    return name


def normalize_color(raw: str | None) -> str | None:
    if raw is None or raw == "":
        return None
    color = raw.strip().lower()
    if not _COLOR_RE.match(color):
        raise TagError("Colour must be a #rrggbb hex value")
    return color


# SQLite caps bound parameters per statement; chunk long id lists well under it.
_ID_CHUNK = 500


def sync_tags_text(db: Session, asset_ids: list[str]) -> None:
    """Refresh the FTS mirror for the given assets. No-op on an empty list."""
    for start in range(0, len(asset_ids), _ID_CHUNK):
        chunk = asset_ids[start:start + _ID_CHUNK]
        placeholders = ", ".join(f":a{i}" for i in range(len(chunk)))
        params = {f"a{i}": aid for i, aid in enumerate(chunk)}
        db.execute(text(
            f"{_SYNC_TAGS_TEXT_SQL} WHERE id IN ({placeholders}) AND {_DRIFTED_ONLY}"
        ), params)


# ── Ordering ──────────────────────────────────────────────────────────────────

def ordered_tags(tags) -> list[Tag]:
    """The canonical tag order: system tags first, then name case-insensitively.

    The single Python-side comparator, so the API detail view and the exports
    cannot drift apart. `.lower()` matches the NOCASE collation used by
    Asset.tags and list_tags — _NAME_RE restricts names to ASCII, so case folding,
    SQLite's NOCASE and the frontend's localeCompare agree on every legal name.

    Callers pass Asset.tags, which the relationship already returns in this
    order; sorting again is cheap and covers the access paths where relationship
    ordering does not apply (a manually assembled list, a merged result set).
    """
    return sorted(tags, key=lambda t: (not t.is_system, t.name.lower()))


# ── Lookup ────────────────────────────────────────────────────────────────────

def list_tags(db: Session, project_id: str) -> list[Tag]:
    return (
        db.query(Tag)
        .filter(Tag.project_id == project_id)
        .order_by(Tag.is_system.desc(), Tag.name.collate("NOCASE"))
        .all()
    )


def tag_asset_counts(db: Session, project_id: str) -> dict[str, int]:
    """{tag_id: number of assets carrying it} for one project."""
    rows = db.execute(text(
        "SELECT t.id, COUNT(at.asset_id) FROM tags t"
        " LEFT JOIN asset_tags at ON at.tag_id = t.id"
        " WHERE t.project_id = :pid GROUP BY t.id"
    ), {"pid": project_id}).fetchall()
    return {r[0]: r[1] for r in rows}


def get_tag(db: Session, project_id: str, tag_id: str) -> Tag | None:
    """Fetch a tag scoped to its project — never by id alone, so a tag id from
    one project cannot be used against another."""
    return (
        db.query(Tag)
        .filter(Tag.id == tag_id, Tag.project_id == project_id)
        .first()
    )


def get_tag_by_name(db: Session, project_id: str, name: str) -> Tag | None:
    """Resolve a tag by name within a project, case-insensitively.

    uq_tags_project_name is a plain UNIQUE, so SQLite compares it under the
    default BINARY collation and would happily hold both "Recheck" and
    "recheck" — while normalize_name already treats reserved names
    case-insensitively. Matching the same way here is what makes create answer
    409, rename report a clash, and attach-by-name reuse the tag the operator
    meant instead of quietly minting a second one beside it.

    The ordering only matters if two case variants already exist; a system row
    wins so the read-only check still fires, then the oldest, so repeated calls
    resolve to the same tag rather than whichever the planner reaches first.
    """
    return (
        db.query(Tag)
        .filter(Tag.project_id == project_id, func.lower(Tag.name) == name.lower())
        .order_by(Tag.is_system.desc(), Tag.created_at, Tag.id)
        .first()
    )


# ── Mutation ──────────────────────────────────────────────────────────────────

def create_tag(db: Session, project_id: str, name: str, color: str | None) -> Tag:
    tag = Tag(project_id=project_id, name=name, color=color, is_system=False)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def update_tag(db: Session, tag: Tag, name: str | None, color: str | None,
               color_set: bool) -> Tag:
    if name is not None:
        tag.name = name
    if color_set:
        tag.color = color
    db.commit()
    db.refresh(tag)
    if name is not None:
        # A rename changes the indexed text of every asset carrying the tag.
        sync_tags_text(db, _asset_ids_for_tag(db, tag.id))
        db.commit()
    return tag


def delete_tag(db: Session, tag: Tag) -> None:
    asset_ids = _asset_ids_for_tag(db, tag.id)
    db.execute(text("DELETE FROM asset_tags WHERE tag_id = :tid"), {"tid": tag.id})
    db.delete(tag)
    db.commit()
    sync_tags_text(db, asset_ids)
    db.commit()


def ensure_system_tag(db: Session, project_id: str, name: str) -> Tag:
    """Get-or-create a system tag. Used by the backend-side discovery paths
    (manual insert, project seeding); the engine has its own copy."""
    tag = get_tag_by_name(db, project_id, name)
    if tag:
        return tag
    tag = Tag(project_id=project_id, name=name, is_system=True)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def assign_tag(db: Session, asset_id: str, tag_id: str) -> None:
    db.execute(
        text("INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES (:a, :t)"),
        {"a": asset_id, "t": tag_id},
    )
    sync_tags_text(db, [asset_id])
    db.commit()


def assign_tag_bulk(db: Session, asset_ids: list[str], tag_id: str) -> None:
    """Attach one tag to many assets in a single commit.

    One executemany rather than a statement per id: the seed and recon paths
    hand this whole result sets, and a CIDR expansion hands it up to
    asset_service.MAX_CIDR_HOSTS ids at once. Same statement, same semantics —
    OR IGNORE still absorbs the ids that already carry the tag, including a
    repeat inside the list itself.
    """
    if not asset_ids:
        return
    db.execute(
        text("INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES (:a, :t)"),
        [{"a": asset_id, "t": tag_id} for asset_id in asset_ids],
    )
    sync_tags_text(db, asset_ids)
    db.commit()


def unassign_tag(db: Session, asset_id: str, tag_id: str) -> None:
    db.execute(
        text("DELETE FROM asset_tags WHERE asset_id = :a AND tag_id = :t"),
        {"a": asset_id, "t": tag_id},
    )
    sync_tags_text(db, [asset_id])
    db.commit()


def apply_system_tag(db: Session, project_id: str, asset_id: str, name: str) -> None:
    """Attach a system tag, creating it for the project if needed."""
    tag = ensure_system_tag(db, project_id, name)
    assign_tag(db, asset_id, tag.id)


def _asset_ids_for_tag(db: Session, tag_id: str) -> list[str]:
    rows = db.execute(
        text("SELECT asset_id FROM asset_tags WHERE tag_id = :tid"), {"tid": tag_id}
    ).fetchall()
    return [r[0] for r in rows]


# ── Derived "New!" ────────────────────────────────────────────────────────────

def latest_recon_scan_ids(db: Session, project_ids: list[str]) -> dict[str, str]:
    """{project_id: id of its most recently started recon job}.

    Keyed on started_at rather than created_at so a job sitting in the queue does
    not retire the previous run's "New!" markers before it has found anything.
    Status is deliberately ignored: a cancelled or timed-out recon still
    checkpoints assets to disk, and those assets are genuinely new.
    """
    if not project_ids:
        return {}
    placeholders = ", ".join(f":p{i}" for i in range(len(project_ids)))
    params = {f"p{i}": pid for i, pid in enumerate(project_ids)}
    rows = db.execute(text(
        f"SELECT j.project_id, j.id FROM scan_jobs j WHERE j.scan_type = 'recon'"
        f" AND j.started_at IS NOT NULL AND j.project_id IN ({placeholders})"
        f" AND j.started_at = ("
        f"   SELECT MAX(started_at) FROM scan_jobs WHERE project_id = j.project_id"
        f"   AND scan_type = 'recon' AND started_at IS NOT NULL)"
    ), params).fetchall()
    return {r[0]: r[1] for r in rows}


def decorate_assets(db: Session, assets: list[Asset]) -> list[Asset]:
    """Set .is_new on each asset. Handles a mixed-project list (global search)."""
    if not assets:
        return assets
    latest = latest_recon_scan_ids(db, list({a.project_id for a in assets}))
    for asset in assets:
        asset.is_new = bool(
            asset.first_seen_scan_id
            and asset.first_seen_scan_id == latest.get(asset.project_id)
        )
    return assets
