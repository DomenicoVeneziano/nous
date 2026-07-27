# Nous API Reference

Base URL: `http://localhost:8000`
All endpoints are prefixed with the base URL — no `/api` prefix.

---

## Authentication

All protected endpoints require one of:

```
Authorization: Bearer <token>
X-API-Key: <api_key>
```

| Credential | Format | Scope |
|---|---|---|
| JWT | `eyJ...` (obtained from `/auth/login`) | Session-based; expires per `JWT_EXPIRY_HOURS` |
| API key (edit) | `nous_<64hex>` | Equivalent to admin — full read/write |
| API key (view) | `nous_<64hex>` | Equivalent to viewer — read-only |

**Auth levels used in this document:**
- `ADMIN` — requires admin JWT or edit API key
- `VIEWER` — requires any valid credential
- `PUBLIC` — no authentication

---

## Auth

### `POST /auth/login`
`PUBLIC` · Obtain a JWT token.

**Body** `application/json`
```json
{ "username": "<str>", "password": "<str>" }
```
**Response** `200`
```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```
**Errors:** `401` invalid credentials · `429` too many failed attempts from this IP
(includes a `Retry-After` header)

---

## API Keys

### `POST /api-keys/`
`VIEWER` · Create an API key. Viewers may only create `view` keys.

**Body**
```json
{ "name": "CI pipeline", "key_type": "edit" | "view" }
```
**Response** `201` — full key shown **once only**
```json
{
  "id": "<uuid>", "name": "CI pipeline", "key_type": "edit",
  "key_prefix": "nous_a1b2c3d4",
  "created_at": "<iso>", "last_used_at": null, "is_active": true,
  "full_key": "nous_<64hex>"
}
```
**Errors:** `403` viewer requesting edit key

---

### `GET /api-keys/`
`VIEWER` · List own API keys. Returns active keys for the authenticated user only,
newest first.

**Response** `200` `ApiKeyOut[]` (same as above, without `full_key`)

---

### `PATCH /api-keys/{key_id}`
`VIEWER` · Rename a key. Ownership enforced.

**Body** `{ "name": "<str>" }`
**Response** `200` `ApiKeyOut`
**Errors:** `404` not found or not owned

---

### `DELETE /api-keys/{key_id}`
`VIEWER` · Permanently delete a key. Ownership enforced.

**Response** `204`
**Errors:** `404` not found or not owned

---

## Projects

### `GET /projects/`
`VIEWER` · List all projects.

**Response** `200` `ProjectOut[]`

---

### `POST /projects/`
`ADMIN` · Create a project.

**Body**
```json
{
  "title": "<str>",
  "root_domains": ["example.com"],
  "description": "<str|null>",
  "subdomains": []
}
```
**Response** `201` `ProjectOut`

---

### `GET /projects/{project_id}`
`VIEWER` · Get a single project.

**Response** `200` `ProjectOut`
**Errors:** `404`

---

### `PUT /projects/{project_id}`
`ADMIN` · Update project fields (all optional).

**Body** same shape as `POST /projects/`, all fields optional
**Response** `200` `ProjectOut`

---

### `DELETE /projects/{project_id}`
`ADMIN` · Delete a project.

**Response** `204`

---

### `POST /projects/bulk-delete`
`ADMIN` · Delete multiple projects.

**Body** `{ "project_ids": ["<uuid>", ...] }`
**Response** `200` `{ "deleted": <int> }`

---

### `POST /projects/{project_id}/icon`
`ADMIN` · Upload project icon. Accepted: PNG, JPEG, GIF, WebP. Max 2 MB. Replaces
any existing icon.

**Body** `multipart/form-data` field `file`
**Response** `200` `{ "icon": "<filename>" }` (e.g. `icon.png`)
**Errors:** `404` project not found · `400` invalid image type or file over 2 MB

---

### `GET /projects/{project_id}/icon`
`VIEWER` · Download project icon.

**Response** `200` image bytes
**Errors:** `404` project has no icon, or the stored file is missing

---

### `DELETE /projects/{project_id}/icon`
`ADMIN` · Delete project icon.

**Response** `200` `{ "status": "ok" }`
**Errors:** `404` project not found

---

## Assets

All asset endpoints are scoped under `/projects/{project_id}/assets`.

### `GET /projects/{project_id}/assets/`
`VIEWER` · List assets (paginated).

**Query params**
| Param | Default | Max |
|---|---|---|
| `limit` | 500 | 5000 |
| `offset` | 0 | — |

**Response** `200` `AssetOut[]`

---

### `GET /projects/{project_id}/assets/count`
`VIEWER` · Asset count for a project.

**Response** `200` `{ "count": <int> }`

---

### `GET /projects/{project_id}/assets/{asset_id}`
`VIEWER` · Get a single asset.

**Response** `200` `AssetOut`
**Errors:** `404`

---

### `GET /projects/{project_id}/assets/{asset_id}/export`
`VIEWER` · Download a single asset as a formatted `<asset>.json` snapshot holding
everything the detail view shows: metadata, tags, technologies, flattened DNS
records, crawled and archived endpoints, the stored response body, and findings.

**Response** `200` file download (`application/json`, filename derived from the
asset hostname)
```json
{
  "asset": "sub.example.com",
  "asset_type": "subdomain",
  "exported_at": "<iso>",
  "identifiers": { "id": "<uuid>", "project_id": "<uuid>" },
  "metadata": {
    "status_code": 200, "title": "<str|null>", "content_length": 1234,
    "redirects_to": null, "first_seen": "<iso|null>",
    "date_scanned": "<iso|null>", "last_crawl_at": "<iso|null>", "is_new": false
  },
  "tags": [{ "name": "Passive", "is_system": true }],
  "technologies": ["nginx"],
  "dns_records": [],
  "endpoints": { "crawled": [], "archived": [] },
  "screenshot_path": null,
  "response": { "path": "<str>", "content": "<str|null>" },
  "findings": [
    { "title": "<str>", "severity": "<str>", "body": "<str>",
      "created_at": "<iso|null>", "updated_at": "<iso|null>" }
  ]
}
```
`response` is `null` when the asset has no stored response file. Findings are
ordered by creation date ascending.
**Errors:** `404` asset not found

---

### `POST /projects/{project_id}/assets/`
`ADMIN` · Manually create an asset. The `Manual` discovery-source tag is attached
automatically — there is no request field for it.

**Body**
```json
{
  "asset": "sub.example.com",
  "asset_type": "subdomain" | "ip",
  "status_code": 200,
  "title": "<str|null>",
  "content_length": 1234,
  "technologies": ["nginx", "WordPress"],
  "dns_records": [],
  "crawled_urls": { "crawling": [], "archived": [] }
}
```
All fields except `asset` are optional; `asset_type` defaults to `subdomain`.
A bare `crawled_urls` array is accepted for compatibility and read as
`{ "crawling": [...], "archived": [] }`.
**Response** `201` `AssetOut`
**Errors:** `404` project not found · `409` asset already exists in this project ·
`422` empty `asset` value

---

### `PUT /projects/{project_id}/assets/{asset_id}`
`ADMIN` · Update asset fields (all optional). Only fields present in the body are
written. Tags are not editable here — use the tag endpoints below.

**Body** same shape as POST, all fields optional
**Response** `200` `AssetOut`
**Errors:** `404` asset not found

---

### `DELETE /projects/{project_id}/assets/{asset_id}`
`ADMIN` · Delete an asset.

**Response** `204`

---

### `DELETE /projects/{project_id}/assets/{asset_id}/screenshot`
`ADMIN` · Delete an asset's screenshot — removes the file on disk and clears
`screenshot_path`.

**Response** `204`
**Errors:** `404` asset not found

---

## Tags

Tags are per-project labels attached to assets. Two kinds share one namespace,
separated by the `is_system` flag:

- **User tags** — free-form triage labels under full CRUD.
- **System tags** — discovery-source markers written by the engine, recording how
  an asset was found: `Passive`, `Bruteforce`, `Permutations`, `Crawling`,
  `Redirect`, `Manual`, `Seed`. They are read-only over the API: they cannot be
  created, renamed, recoloured, deleted, attached, or detached. Any such attempt
  returns `403`.

`New!` is reserved and never stored. It is derived per request by comparing an
asset's originating scan to the project's most recent recon job, and surfaces as
the `is_new` boolean on `AssetOut` rather than as a row in the tag list. Creating
a tag by that name is rejected with `422`.

**Name rules:** trimmed, internal whitespace collapsed, at most 40 characters, and
limited to letters, digits, spaces and `. _ - + # / !`. Names are unique per
project, compared case-insensitively.
**Colour rules:** `#rrggbb` hex, or `null`/`""` for the default chip colour.

### `GET /projects/{project_id}/tags`
`VIEWER` · List a project's tags with per-tag asset counts. System tags sort
first, then by name.

**Response** `200` `TagWithCount[]`
**Errors:** `404` project not found

---

### `POST /projects/{project_id}/tags`
`ADMIN` · Create a user tag.

**Body**
```json
{ "name": "Recheck", "color": "#7c5cff" }
```
`color` is optional.
**Response** `201` `TagOut`
**Errors:** `404` project not found · `409` name already used in this project ·
`422` invalid name/colour, or a name reserved for `New!` or a discovery source

---

### `PUT /projects/{project_id}/tags/{tag_id}`
`ADMIN` · Rename or recolour a user tag. Omitted fields are left alone; an
explicit `"color": null` clears the colour back to the default chip colour.

**Body** `{ "name": "<str>", "color": "<#rrggbb|null>" }` — both optional
**Response** `200` `TagOut`
**Errors:** `404` project or tag not found · `403` tag is a discovery-source tag ·
`409` name already used in this project · `422` invalid name/colour

---

### `DELETE /projects/{project_id}/tags/{tag_id}`
`ADMIN` · Delete a user tag and detach it from every asset carrying it.

**Response** `204`
**Errors:** `404` project or tag not found · `403` tag is a discovery-source tag

---

### `POST /projects/{project_id}/assets/{asset_id}/tags`
`ADMIN` · Attach a tag to an asset. Either reference an existing tag by
`tag_id`, or pass a `name` to create-and-attach in one call. Supplying `tag_id`
together with `name` or `color` is rejected rather than silently ignored.
Attaching a tag the asset already carries is a no-op.

**Body**
```json
{ "tag_id": "<uuid>" }
```
or
```json
{ "name": "Recheck", "color": "#7c5cff" }
```
**Response** `200` `AssetOut` — the asset with its refreshed `tags` array
**Errors:** `404` project, asset, or tag not found · `403` tag is a
discovery-source tag (by id or by name) · `409` name collision during
create-and-attach · `422` neither `tag_id` nor `name` given, both given, or the
name/colour is invalid or reserved

---

### `DELETE /projects/{project_id}/assets/{asset_id}/tags/{tag_id}`
`ADMIN` · Detach a tag from an asset. The tag itself is kept. Detaching a tag the
asset does not carry is a no-op.

**Response** `200` `AssetOut` — the asset with its refreshed `tags` array
**Errors:** `404` project, asset, or tag not found · `403` tag is a
discovery-source tag

---

## Findings

Findings are security observations attached to a specific asset. All endpoints are scoped under `/projects/{project_id}/assets/{asset_id}/findings`.

### `GET /projects/{project_id}/assets/{asset_id}/findings/`
`VIEWER` · List all findings for an asset, ordered by creation date ascending.

**Response** `200` `FindingOut[]`
**Errors:** `404` asset not found

---

### `POST /projects/{project_id}/assets/{asset_id}/findings/`
`ADMIN` · Create a finding.

**Body**
```json
{
  "title": "Open Redirect",
  "severity": "informative" | "low" | "medium" | "high" | "critical",
  "body": "## Summary\n\nMarkdown-formatted write-up."
}
```
`body` is optional (defaults to `""`).
**Response** `201` `FindingOut`
**Errors:** `404` asset not found · `422` validation failure

---

### `PUT /projects/{project_id}/assets/{asset_id}/findings/{finding_id}`
`ADMIN` · Update a finding (all fields optional). Always updates `updated_at`.

**Body** same shape as `POST`, all fields optional
**Response** `200` `FindingOut`
**Errors:** `404` asset or finding not found

---

### `DELETE /projects/{project_id}/assets/{asset_id}/findings/{finding_id}`
`ADMIN` · Permanently delete a finding.

**Response** `204`
**Errors:** `404`

---

## Scans

### `POST /scans/`
`ADMIN` · Enqueue a scan job.

**Body**
```json
{
  "project_id": "<uuid>",
  "scan_type": "recon" | "tech" | "crawl",
  "asset_ids": ["<uuid>", ...],
  "scope_domains": ["*.example.com", ...]
}
```
- `asset_ids` — optional; omit to target all project assets. Ignored for `recon`.
- `scope_domains` — optional, `recon` only. Subset of the project's `root_domains` to scan. Omit or set to `null` to scan all root domains. Each entry must exactly match a value in the project's `root_domains` list (wildcards included, e.g. `*.example.com`). Returns `422` if any domain is not in the project's scope.

**Response** `201` `ScanOut`
**Errors:** `404` project not found · `422` `scope_domains` contains domains not in project scope

---

### `GET /scans/queue`
`VIEWER` · Active scan jobs (status `queued` or `running`), ordered by queue position.

**Response** `200` `ScanOut[]`

---

### `GET /scans/history`
`VIEWER` · Last 100 completed jobs (status `done`, `failed`, `cancelled`, `timed_out`).

**Response** `200` `ScanOut[]`

---

### `DELETE /scans/history`
`ADMIN` · Clear all scan history.

**Response** `204`

---

### `DELETE /scans/output`
`ADMIN` · Clear the live scan-output replay buffer and notify every connected
consumer with an `output_cleared` event. Scan jobs themselves are untouched.

**Response** `204`

---

### `PATCH /scans/{job_id}/position`
`ADMIN` · Reorder a queued job.

**Body** `{ "queue_pos": <int> }`
**Response** `200` `ScanOut`
**Errors:** `404` not found · `400` job not in `queued` status

---

### `DELETE /scans/{job_id}`
`ADMIN` · Cancel a queued/running job, or delete a completed job from history.

**Response** `204`
**Errors:** `404`

---

## Search

### `GET /search/`
`VIEWER` · Structured search across assets, FTS5-prefiltered where possible.

**Query params**
| Param | Required | Description |
|---|---|---|
| `query` | yes | Structured query string (min length 1) |
| `project_id` | no | Scope to a single project |
| `limit` | no (default: uncapped, min 1) | |
| `offset` | no (default 0) | |

**Query syntax** — `field:value` clauses joined by `AND` / `OR` / `NOT` / `XOR`.
A value may be plain text (case-insensitive substring), `"quoted text"`, or a
`/regex/` (max 256 characters). Unknown fields are ignored.

| Field | Matches against |
|---|---|
| `hostname` | asset hostname or IP |
| `tech` | each detected technology |
| `status` | HTTP status code |
| `title` | page title |
| `content_length` | response length |
| `dns` | each DNS record |
| `url` | crawled and archived endpoints |
| `tag` | tag names, including the derived `New!` marker |
| `type` | `subdomain` \| `ip` |
| `date` | last tech-analysis timestamp |
| `content` / `header` / `body` | stored response file (whole / headers / body) |
| `severity` | severity of the asset's findings |
| `vuln` | name of a stored vuln pattern, expanded to its checks |

**Response** `200` `AssetSearchOut[]` — `AssetOut` plus a `highlights` array
(capped at 20 per asset)

---

### `GET /search/findings`
`VIEWER` · Search findings across projects.

**Query params**
| Param | Required | Description |
|---|---|---|
| `query` | no | Free-text search string |
| `severity` | no | `informative` \| `low` \| `medium` \| `high` \| `critical` |
| `project_id` | no | Scope to a single project |
| `limit` | no (default 100, max 1000) | |
| `offset` | no (default 0) | |

**Response** `200` `FindingSearchOut[]` — `FindingOut` plus `asset_hostname`
**Errors:** `422` `severity` outside the allowed set

---

### `GET /search/export`
`VIEWER` · Export assets as a file download, capped at 10 000 rows.

**Query params**
| Param | Values | Default |
|---|---|---|
| `query` | structured query string | `""` — empty exports every asset in scope |
| `project_id` | `<uuid>` | none (all projects) |
| `format` | `json` \| `csv` | `json` |

`limit` and `offset` are not accepted here.

**Response** `200` file download (`export.json` or `export.csv`). Both formats
carry the same columns: `asset`, `status_code`, `title`, `content_length`,
`technologies`, `dns_records`, `tags`, `first_seen`, `last_scanned`,
`last_crawled`. Tag names are listed system-first, then alphabetically.
**Errors:** `422` `format` outside `json` / `csv`

---

## Files

### `GET /files/tree`
`VIEWER` · Directory listing of a project's data folder.

**Query params** `project_id=<uuid>` (required)
**Response** `200` `{ "files": ["<relative_path>", ...] }`
**Errors:** `404` project directory not found

---

### `GET /files/content`
`VIEWER` · Read a file inside `data/projects/`.

**Query params** `path=<relative_path>` (required, e.g. `<project_id>/subdomains.txt`)
**Response** `200` `text/plain`
**Errors:** `403` path traversal attempt · `404` file not found

---

### `PUT /files/content`
`ADMIN` · Write a file inside `data/projects/`.

**Body** `{ "path": "<relative_path>", "content": "<str>" }`
**Response** `200` `{ "status": "ok", "path": "<str>" }`
**Errors:** `403` path traversal · `404` parent directory not found

---

### `GET /files/image`
`VIEWER` · Serve a binary image (e.g. a tech-analysis screenshot) from `data/projects/`.

**Query params** `path=<relative_path>` (required, e.g. `<project_id>/screenshots/<host>.png`)
**Response** `200` image bytes (`image/png`, `image/jpeg`, `image/webp`)
**Errors:** `403` path traversal · `400` not an allowed image type · `404` file not found

---

## Settings

### `GET /settings/scan-config`
`VIEWER` · Get current scan configuration.

**Response** `200`
```json
{
  "recon_timeout": 3600,
  "tech_timeout": 0,
  "crawl_timeout": 1200,
  "crawl_max_pages": 10,
  "wordlist_path": "<str>",
  "resolvers_path": "<str>",
  "dns_bruteforce_enabled": false,
  "tech_screenshots_enabled": false,
  "tech_rate_limit_delay": 3.0,
  "dns_rate_limit_delay": 0.0,
  "crawl_rate_limit_delay": 0.0
}
```

---

### `PUT /settings/scan-config`
`ADMIN` · Update scan configuration (all fields optional).

**Body** same shape as above, all optional. When `tech_screenshots_enabled` is
`true`, a tech-analysis scan captures a screenshot of each asset after page load.
**Response** `200` `{ "updated": { <changed_fields> } }`

---

### `GET /settings/proxy-config`
`VIEWER` · Get the current proxy configuration. The password is never returned;
`password_set` indicates whether one is stored.

**Response** `200`
```json
{
  "enabled": false,
  "scheme": "http",
  "host": "",
  "port": 8080,
  "username": "",
  "password_set": false,
  "recon": false,
  "tech": false,
  "crawl": false
}
```
`scheme`: `http` | `https` | `socks5`. The `recon` / `tech` / `crawl` flags select
which scan types route through the proxy (the rest connect directly).

---

### `PUT /settings/proxy-config`
`ADMIN` · Update proxy configuration (all fields optional). Persisted to the DB
and applied to subsequently queued scans. Omit `password` to keep the stored one;
send `"password": ""` to clear it.

**Body** `{ "enabled", "scheme", "host", "port", "username", "password", "recon", "tech", "crawl" }`
**Response** `200` proxy config (same shape as GET)
**Errors:** `400` host required when enabling · `422` invalid scheme/port/host

---

### `POST /settings/proxy-config/test`
`ADMIN` · Best-effort TCP reachability check against a proxy endpoint.

**Body** `{ "host": "<str>", "port": <int> }`
**Response** `200` `{ "reachable": <bool>, "message": "<str>" }`
**Errors:** `400` invalid host/port

---

### `GET /settings/users`
`ADMIN` · List all users.

**Response** `200` `UserOut[]` `[{ "id", "username", "role" }]`

---

### `POST /settings/users`
`ADMIN` · Create a user.

**Body** `{ "username": "<str>", "password": "<str>", "role": "admin" | "viewer" }`
**Response** `201` `UserOut`
**Errors:** `400` username taken

---

### `PUT /settings/users/{user_id}`
`ADMIN` · Update a user (all fields optional).

**Body** `{ "username": "<str>", "role": "admin"|"viewer", "password": "<str>" }`
**Response** `200` `UserOut`
**Errors:** `404` · `400` username conflict

---

### `DELETE /settings/users/{user_id}`
`ADMIN` · Delete a user.

**Response** `204`
**Errors:** `404`

---

## Stats

### `GET /stats/technologies`
`VIEWER` · Technology distribution across all assets.

**Response** `200` `[{ "name": "<str>", "count": <int> }]` sorted by count descending

---

## Vuln Patterns

Named bundles of regex checks, reusable from search via the `vuln:<name>` field.
Each check pairs a searchable `field` with a `regex` evaluated against it. Some
patterns ship as defaults and cannot be deleted.

### `GET /vuln-patterns/`
`VIEWER` · List all patterns.

**Response** `200` `VulnPatternOut[]`

---

### `POST /vuln-patterns/`
`ADMIN` · Create a pattern.

**Body**
```json
{
  "name": "takeover_candidate",
  "description": "Dangling CNAME indicators",
  "checks": [{ "field": "body", "regex": "NoSuchBucket" }]
}
```
`name`: 1–64 characters, `[a-z0-9_]` only. `description`: 1–256 characters.
`checks`: at least one entry.
**Response** `201` `VulnPatternOut`
**Errors:** `409` name already exists · `422` validation failure

---

### `PUT /vuln-patterns/{pattern_id}`
`ADMIN` · Update a pattern's description and/or checks. The name is immutable.

**Body** `{ "description": "<str>", "checks": [...] }` — both optional
**Response** `200` `VulnPatternOut`
**Errors:** `404` not found · `422` validation failure

---

### `DELETE /vuln-patterns/{pattern_id}`
`ADMIN` · Delete a pattern.

**Response** `204`
**Errors:** `404` not found · `403` default patterns cannot be deleted

---

### `POST /vuln-patterns/{pattern_id}/test`
`VIEWER` · Run a pattern against one project and report what it would match.

**Query params** `project_id=<uuid>` (required)
**Response** `200`
```json
{
  "pattern_id": "<uuid>", "pattern_name": "<str>",
  "match_count": <int>, "matched_asset_ids": ["<uuid>", ...]
}
```
**Errors:** `404` pattern not found · `422` `project_id` missing

---

## Health

### `GET /health`
`PUBLIC` · Liveness probe.

**Response** `200` `{ "status": "ok" }`

---

## WebSocket

### `WS /ws/scan`
Real-time scan events. Every connection must authenticate — anonymous
connections are rejected (closed with code `4401`):

- **Consumer** (frontend): connect with `?token=<JWT>`. Receives the replay
  buffer and all broadcast events; any frames it sends are ignored.
- **Producer** (engine): connects with `?engine_token=<secret>` matching
  `ENGINE_WS_SECRET` (or the value derived from `SECRET_KEY` when unset). May
  push events but never receives broadcasts.

**Inbound event shape**
```json
{ "type": "<event_type>", "data": { ... } }
```

| Event | Data fields | Emitted when |
|---|---|---|
| `job_started` | `job_id`, `scan_type` | Worker picks up a job |
| `scan_line` | `job_id`, `line` | Scan stdout line |
| `asset_update` | `job_id`, `domain`, `status_code`, `title`, `technologies`, `redirects_to` | Tech/crawl result |
| `job_complete` | `job_id`, `scan_type`, `project_id`, `new_assets` | Job finished |
| `job_failed` | `job_id`, `error` | Job errored |
| `output_cleared` | — (empty object) | `DELETE /scans/output` emptied the buffer |

---

## Shared Schemas

### `ProjectOut`
```
id, title, description, root_domains[], subdomains[], status,
last_scan_date, last_scan_duration_s, asset_count, tech_count,
is_master, icon, logo_path
```
`status`: `to_scan` | `scanning` | `scanned`

### `AssetOut`
```
id, project_id, asset, asset_type, dns_records[], technologies[],
status_code, title, content_length, redirects_to, response_file_path,
screenshot_path, crawled_urls{}, date_scanned, first_seen, last_crawl_at,
tags[], is_new
```
`asset_type`: `subdomain` | `ip`
`redirects_to`: destination host when the asset issues a cross-host redirect, else `null`
`screenshot_path`: path (relative to `data/projects/`) of the asset's screenshot, else `null` — fetch via `GET /files/image`
`crawled_urls`: `{ "crawling": [<url>, ...], "archived": [<url>, ...] }` — endpoints
found by the crawler and endpoints recovered from archives, kept apart. Both keys
are always present; each list is deduplicated in insertion order.
`date_scanned`: last tech analysis · `last_crawl_at`: last crawl
`tags`: `TagOut[]`, system tags first then alphabetical
`is_new`: derived, never stored — `true` when the asset was first seen by the
project's most recent recon job. Renders as the reserved `New!` marker.

### `TagOut`
```
id, project_id, name, color, is_system
```
`color`: `#rrggbb`, or `null` for the default chip colour
`is_system`: `true` for a read-only discovery-source tag

### `TagWithCount`
```
id, project_id, name, color, is_system, asset_count
```
`asset_count`: assets in this project carrying the tag

### `ScanOut`
```
id, project_id, scan_type, status, queue_pos, asset_ids[], scope_domains[],
created_at, started_at, finished_at, duration_s, log_path, error_msg, config
```
`scan_type`: `recon` | `tech` | `crawl`
`status`: `queued` | `running` | `done` | `failed` | `cancelled` | `timed_out`
`config`: scan settings snapshotted at enqueue time and handed to the engine, else `null`

### `ApiKeyOut`
```
id, name, key_type, key_prefix, created_at, last_used_at, is_active
```
`key_type`: `edit` | `view`

### `FindingOut`
```
id, asset_id, project_id, title, severity, body, created_at, updated_at
```
`severity`: `informative` | `low` | `medium` | `high` | `critical`
`body`: markdown string

### `FindingSearchOut`
```
<FindingOut fields>, asset_hostname
```

### `AssetSearchOut`
```
<AssetOut fields>, highlights[]
```
Each highlight is `{ field, source, snippet, start, end, index }`:
`field` is the queried field, `source` the concrete field the span lives in (they
differ only for `vuln`), `start`/`end` are offsets into `snippet`, and `index` is
the list position for list-valued fields (`null` otherwise).

### `VulnPatternOut`
```
id, name, description, checks[], is_default, created_at, updated_at
```
`checks`: `[{ "field": "<searchable field>", "regex": "<str>" }]`
`is_default`: shipped pattern — cannot be deleted

### Common HTTP errors
| Code | Meaning |
|---|---|
| `400` | Bad request / validation error |
| `401` | Missing or invalid credential |
| `403` | Insufficient permission, or the resource is read-only |
| `404` | Resource not found |
| `409` | Conflict — name or asset already exists |
| `422` | Pydantic validation failure (body schema or query params) |
| `429` | Login rate limit — too many failed attempts |
