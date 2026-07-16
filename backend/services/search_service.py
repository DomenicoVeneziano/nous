# backend/services/search_service.py
import re
from sqlalchemy.orm import Session
from sqlalchemy import text
from models.asset import Asset
from config import settings
from schemas.asset_search import Highlight

# Max regex pattern length to prevent ReDoS
MAX_PATTERN_LENGTH = 256

# Max highlights returned per asset and max spans collected per field
MAX_HIGHLIGHTS_PER_ASSET = 20
MAX_SPANS_PER_FIELD = 10

# Characters of context on each side of a file-backed match
_FILE_SNIPPET_PAD = 80

# Strict field whitelist
VALID_FIELDS = {
    "hostname", "tech", "status", "title", "content", "content_length", "dns",
    "url", "type", "date", "header", "body", "severity",
    "vuln",  # expanded to pattern checks at search time
}

# Fields that search response files on disk (slow)
_FILE_FIELDS = {"content", "header", "body"}

# Fields excluded from FTS5 pre-filter
_NO_FTS_FIELDS = _FILE_FIELDS | {"url", "type", "date", "severity", "vuln"}


_OPERATORS = {"AND", "OR", "NOT", "XOR"}


def _tokenize_query(raw: str) -> list[str]:
    """
    Scan left-to-right and split into clause tokens and operator tokens.
    Respects:
      - "quoted strings"  — operators inside quotes are not split points
      - /regex patterns/  — operators inside /…/ are not split points
    Returns a flat list like: ['tech:nginx', 'AND', 'status:200', 'OR', 'hostname:/^api\\./' ]
    """
    tokens: list[str] = []
    buf: list[str] = []
    buf_has_colon = False  # tracks whether current token buffer contains ':'
    i = 0
    n = len(raw)

    while i < n:
        c = raw[i]

        # --- quoted string value: consume until closing " ---
        if c == '"':
            j = raw.find('"', i + 1)
            end = (j + 1) if j != -1 else n
            buf.append(raw[i:end])
            i = end
            continue

        # --- regex value /…/: only treat as regex delimiter when we are
        #     already inside a `field:` token (buf contains a colon) ---
        if c == '/' and buf_has_colon:
            j = raw.find('/', i + 1)
            end = (j + 1) if j != -1 else n
            buf.append(raw[i:end])
            i = end
            continue

        # --- check for a stand-alone boolean operator ---
        matched_op = None
        for op in _OPERATORS:
            if raw[i:].startswith(op):
                after = i + len(op)
                # must be followed by whitespace or end-of-string, and
                # preceded by whitespace or start-of-string
                before_ok = (i == 0 or raw[i - 1] in (' ', '\t'))
                after_ok  = (after >= n or raw[after] in (' ', '\t'))
                if before_ok and after_ok:
                    matched_op = op
                    break

        if matched_op:
            clause = ''.join(buf).strip()
            if clause:
                tokens.append(clause)
            buf = []
            buf_has_colon = False
            tokens.append(matched_op)
            i += len(matched_op)
            continue

        if c == ':':
            buf_has_colon = True
        buf.append(c)
        i += 1

    if buf:
        clause = ''.join(buf).strip()
        if clause:
            tokens.append(clause)

    return tokens


def _parse_query(raw_query: str) -> list[dict]:
    """
    Parse a structured query string into a list of filter clauses.
    Supports: hostname:/regex/, tech:value, status:200, AND/OR/NOT/XOR
    Quoted strings and /regex/ delimiters are respected — operators inside
    them are never treated as boolean operators.
    Returns list of {field, value, is_regex, operator}
    """
    clauses = []
    tokens = _tokenize_query(raw_query)

    current_op = "AND"
    for token in tokens:
        if token in _OPERATORS:
            current_op = token
            continue

        # Parse field:value — value may be quoted or a /regex/
        match = re.match(r'^(\w+):(.+)$', token, re.DOTALL)
        if match:
            field = match.group(1).lower()
            value = match.group(2).strip()

            if field not in VALID_FIELDS:
                current_op = "AND"
                continue

            is_regex = False
            if value.startswith("/") and value.endswith("/") and len(value) > 2:
                value = value[1:-1]
                is_regex = True
            elif value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]

            if not value or len(value) > MAX_PATTERN_LENGTH:
                current_op = "AND"
                continue

            # Validate regex to give early failure rather than silent empty results
            if is_regex:
                try:
                    re.compile(value)
                except re.error:
                    current_op = "AND"
                    continue

            clauses.append({
                "field": field,
                "value": value,
                "is_regex": is_regex,
                "operator": current_op,
            })

        current_op = "AND"

    return clauses


def _read_response_file(asset: Asset) -> str | None:
    """Read the full response file for an asset, returning None if unavailable."""
    if not asset.response_file_path:
        return None
    file_path = settings.DATA_DIR / asset.response_file_path
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _split_response_file(content: str) -> tuple[str, str]:
    """
    Split a response file into (headers_section, body_section).

    File format:
        Status Code: 200
        Headers:
          Key: Value
          ...

        HTML Content:
        <html>...
    """
    headers_part = ""
    body_part = ""

    html_marker = "\nHTML Content:\n"
    marker_idx = content.find(html_marker)
    if marker_idx != -1:
        headers_part = content[:marker_idx]
        body_part = content[marker_idx + len(html_marker):]
    else:
        # Fallback: split on first blank line
        parts = content.split("\n\n", 1)
        headers_part = parts[0] if parts else content
        body_part = parts[1] if len(parts) > 1 else ""

    return headers_part, body_part


def _find_spans(target: str, value: str, is_regex: bool) -> list[tuple[int, int]]:
    """
    Return a list of (start, end) byte offsets for all matches of `value` in `target`.
    Returns an empty list if there are no matches.
    Capped at MAX_SPANS_PER_FIELD to bound CPU/memory for large targets.
    """
    spans: list[tuple[int, int]] = []
    if is_regex:
        try:
            for m in re.finditer(value, target, re.IGNORECASE | re.MULTILINE | re.DOTALL):
                spans.append((m.start(), m.end()))
                if len(spans) >= MAX_SPANS_PER_FIELD:
                    break
        except re.error:
            pass
    else:
        lower_target = target.lower()
        lower_value = value.lower()
        pos = 0
        while len(spans) < MAX_SPANS_PER_FIELD:
            idx = lower_target.find(lower_value, pos)
            if idx == -1:
                break
            spans.append((idx, idx + len(lower_value)))
            pos = idx + 1
    return spans


def _build_window(text: str, start: int, end: int, pad: int = _FILE_SNIPPET_PAD) -> tuple[str, int, int]:
    """
    Extract a context window around [start, end) from `text`.
    Returns (snippet, adj_start, adj_end) where adj_* are offsets into snippet.
    """
    win_start = max(0, start - pad)
    win_end = min(len(text), end + pad)
    snippet = text[win_start:win_end]
    return snippet, start - win_start, end - win_start


def _spans_to_highlights(
    spans: list[tuple[int, int]],
    field: str,
    source: str,
    text: str,
    index: int | None = None,
    windowed: bool = False,
) -> list[Highlight]:
    """Convert raw (start, end) spans into Highlight objects."""
    highlights = []
    for start, end in spans:
        if windowed:
            snippet, adj_start, adj_end = _build_window(text, start, end)
        else:
            snippet = text
            adj_start, adj_end = start, end
        highlights.append(Highlight(
            field=field,
            source=source,
            snippet=snippet,
            start=adj_start,
            end=adj_end,
            index=index,
        ))
    return highlights


def _match_asset(
    asset: Asset,
    clause: dict,
    vuln_checks_map: dict[str, list[dict]] | None = None,
    severity_map: dict[str, set] | None = None,
) -> tuple[bool, list[Highlight]]:
    """
    Check if a single asset matches a clause.
    Returns (matched, highlights) where highlights are empty when not matched
    or when highlight extraction is not applicable (e.g. severity).
    """
    field = clause["field"]
    value = clause["value"]
    is_regex = clause["is_regex"]

    if field == "hostname":
        target = asset.asset or ""
        spans = _find_spans(target, value, is_regex)
        return bool(spans), _spans_to_highlights(spans, field, field, target)

    elif field == "dns":
        records = asset.dns_records or []
        highlights = []
        for i, record in enumerate(records):
            target = str(record)
            spans = _find_spans(target, value, is_regex)
            highlights.extend(_spans_to_highlights(spans, field, field, target, index=i))
        return bool(highlights), highlights

    elif field == "tech":
        techs = asset.technologies or []
        highlights = []
        for i, tech in enumerate(techs):
            spans = _find_spans(tech, value, is_regex)
            highlights.extend(_spans_to_highlights(spans, field, field, tech, index=i))
        return bool(highlights), highlights

    elif field == "status":
        target = str(asset.status_code or "")
        spans = _find_spans(target, value, is_regex)
        return bool(spans), _spans_to_highlights(spans, field, field, target)

    elif field == "title":
        target = asset.title or ""
        spans = _find_spans(target, value, is_regex)
        return bool(spans), _spans_to_highlights(spans, field, field, target)

    elif field == "content_length":
        target = str(asset.content_length or "")
        spans = _find_spans(target, value, is_regex)
        return bool(spans), _spans_to_highlights(spans, field, field, target)

    elif field == "url":
        cu = asset.crawled_urls or {}
        if isinstance(cu, list):
            urls = cu
        else:
            urls = (cu.get("crawling") or []) + (cu.get("archived") or [])
        highlights = []
        for url in urls:
            spans = _find_spans(url, value, is_regex)
            # Highlights are matched back to a rendered URL by snippet text
            # (not list index) so they resolve across both source sections.
            highlights.extend(_spans_to_highlights(spans, field, field, url))
        return bool(highlights), highlights

    elif field == "type":
        target = asset.asset_type or ""
        spans = _find_spans(target, value, is_regex)
        return bool(spans), _spans_to_highlights(spans, field, field, target)

    elif field == "date":
        target = str(asset.date_scanned) if asset.date_scanned else ""
        spans = _find_spans(target, value, is_regex)
        return bool(spans), _spans_to_highlights(spans, field, field, target)

    elif field in ("content", "header", "body"):
        raw = _read_response_file(asset)
        if raw is None:
            return False, []
        if field == "content":
            target = raw
        else:
            headers_section, body_section = _split_response_file(raw)
            target = headers_section if field == "header" else body_section
        spans = _find_spans(target, value, is_regex)
        highlights = _spans_to_highlights(spans, field, field, target, windowed=True)
        return bool(highlights), highlights

    elif field == "vuln":
        if not vuln_checks_map:
            return False, []
        checks = vuln_checks_map.get(value)
        if not checks:
            return False, []
        # Evaluate ALL checks (no early exit) to collect every matching highlight
        any_matched = False
        all_highlights: list[Highlight] = []
        for check in checks:
            check_clause = {
                "field": check["field"],
                "value": check["regex"],
                "is_regex": True,
                "operator": "OR",
            }
            check_matched, check_hls = _match_asset(asset, check_clause, vuln_checks_map)
            if check_matched:
                any_matched = True
                # Relabel field to "vuln" while preserving source = underlying field
                for hl in check_hls:
                    all_highlights.append(Highlight(
                        field="vuln",
                        source=hl.source,
                        snippet=hl.snippet,
                        start=hl.start,
                        end=hl.end,
                        index=hl.index,
                    ))
        return any_matched, all_highlights

    elif field == "severity":
        if severity_map is None:
            return False, []
        asset_ids = severity_map.get(value.lower(), set())
        if asset.id not in asset_ids:
            return False, []
        # Sentinel highlight: no textual span, just records that this severity matched
        hl = Highlight(field="severity", source="severity", snippet=value, start=0, end=len(value))
        return True, [hl]

    return False, []


def _build_vuln_checks_map(db: Session, clauses: list[dict]) -> dict[str, list[dict]]:
    """Load checks for all vuln pattern names referenced in clauses."""
    from models.vuln_pattern import VulnPattern
    names = {c["value"] for c in clauses if c["field"] == "vuln"}
    if not names:
        return {}
    patterns = db.query(VulnPattern).filter(VulnPattern.name.in_(names)).all()
    return {p.name: p.checks for p in patterns}


def _build_severity_map(db: Session, clauses: list[dict]) -> dict[str, set]:
    """Build {severity: set(asset_ids)} for all severity values referenced in clauses."""
    from models.finding import Finding
    severities = {c["value"].lower() for c in clauses if c["field"] == "severity"}
    if not severities:
        return {}
    rows = db.query(Finding.severity, Finding.asset_id).filter(Finding.severity.in_(severities)).all()
    result: dict[str, set] = {sev: set() for sev in severities}
    for sev, asset_id in rows:
        result[sev].add(asset_id)
    return result


def search_assets(
    db: Session,
    query: str,
    project_id: str | None = None,
    limit: int | None = 100,
    offset: int = 0,
) -> list[Asset]:
    """
    Search assets using structured query syntax.
    Uses FTS5 for initial candidate filtering, then applies regex/field matching.
    Each matched asset has a .highlights attribute attached (list[Highlight]).
    """
    clauses = _parse_query(query)

    if not clauses:
        return []

    # Pre-load vuln pattern checks and severity maps
    vuln_checks_map = _build_vuln_checks_map(db, clauses)
    severity_map = _build_severity_map(db, clauses)

    # Try FTS5 pre-filter for eligible fields only
    fts_terms = []
    for c in clauses:
        if c["field"] not in _NO_FTS_FIELDS and not c["is_regex"]:
            fts_terms.append(c["value"])

    if fts_terms:
        fts_query = " OR ".join(f'"{t}"' for t in fts_terms)
        rows = db.execute(
            text("SELECT asset_id FROM asset_fts WHERE asset_fts MATCH :q"),
            {"q": fts_query},
        ).fetchall()
        candidate_ids = [r[0] for r in rows]

        if candidate_ids:
            q = db.query(Asset).filter(Asset.id.in_(candidate_ids))
        else:
            # FTS returned nothing — fall back to a full project scan so that
            # regex clauses and any FTS tokenization mismatches still work.
            # (FTS is an optimisation, not a correctness gate.)
            q = db.query(Asset)
    else:
        q = db.query(Asset)

    if project_id:
        q = q.filter(Asset.project_id == project_id)

    candidates = q.all()

    # Apply detailed matching and collect highlights
    results = []
    for asset in candidates:
        match = True
        asset_highlights: list[Highlight] = []
        for clause in clauses:
            clause_match, clause_hls = _match_asset(asset, clause, vuln_checks_map, severity_map)
            if clause_match:
                asset_highlights.extend(clause_hls)
            op = clause["operator"]

            if op == "AND":
                match = match and clause_match
            elif op == "OR":
                match = match or clause_match
            elif op == "NOT":
                match = match and (not clause_match)
            elif op == "XOR":
                match = match != clause_match

        if match:
            asset.highlights = asset_highlights[:MAX_HIGHLIGHTS_PER_ASSET]
            results.append(asset)

    # limit=None means return every match (no cap), only honouring offset.
    if limit is None:
        return results[offset:]
    return results[offset:offset + limit]
