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

**Request** `application/x-www-form-urlencoded`
```
username=<str>  password=<str>
```
**Response** `200`
```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```
**Errors:** `401` invalid credentials

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
`VIEWER` · List own API keys. Returns keys for the authenticated user only.

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
`ADMIN` · Upload project icon. Accepted: PNG, JPEG, GIF, WebP, SVG. Max 2 MB.

**Body** `multipart/form-data` field `file`
**Response** `200` `{ "icon": "<filename>" }`

---

### `GET /projects/{project_id}/icon`
`PUBLIC` · Download project icon.

**Response** `200` image bytes

---

### `DELETE /projects/{project_id}/icon`
`ADMIN` · Delete project icon.

**Response** `200` `{ "status": "ok" }`

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

### `POST /projects/{project_id}/assets/`
`ADMIN` · Manually create an asset.

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
  "crawled_urls": [],
  "manually_inserted": true
}
```
All fields except `asset` are optional.
**Response** `201` `AssetOut`

---

### `PUT /projects/{project_id}/assets/{asset_id}`
`ADMIN` · Update asset fields (all optional).

**Body** same shape as POST, all fields optional
**Response** `200` `AssetOut`

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
`VIEWER` · Full-text search across assets (SQLite FTS5).

**Query params**
| Param | Required | Description |
|---|---|---|
| `query` | yes | Search string; supports regex |
| `project_id` | no | Scope to a single project |
| `limit` | no (default 100, max 1000) | |
| `offset` | no (default 0) | |

**Response** `200` `AssetOut[]`

---

### `GET /search/export`
`VIEWER` · Export search results as a file download.

**Query params** same as `GET /search/` plus:
| Param | Values | Default |
|---|---|---|
| `format` | `json` \| `csv` | `json` |

**Response** `200` file download (`export.json` or `export.csv`)

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
screenshot_path, crawled_urls[], date_scanned, manually_inserted
```
`asset_type`: `subdomain` | `ip`
`redirects_to`: destination host when the asset issues a cross-host redirect, else `null`
`screenshot_path`: path (relative to `data/projects/`) of the asset's screenshot, else `null` — fetch via `GET /files/image`

### `ScanOut`
```
id, project_id, scan_type, status, queue_pos, asset_ids[], scope_domains[],
created_at, started_at, finished_at, duration_s, log_path, error_msg
```
`scan_type`: `recon` | `tech` | `crawl`
`status`: `queued` | `running` | `done` | `failed` | `cancelled` | `timed_out`

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

### Common HTTP errors
| Code | Meaning |
|---|---|
| `400` | Bad request / validation error |
| `401` | Missing or invalid credential |
| `403` | Insufficient permission |
| `404` | Resource not found |
| `422` | Pydantic validation failure (body schema) |
