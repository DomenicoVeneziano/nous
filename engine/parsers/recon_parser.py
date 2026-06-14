# engine/parsers/recon_parser.py
import re
from urllib.parse import urlparse

_HOSTNAME_RE = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*$')

_STATIC_PATTERN = re.compile(
    r'\.(png|jpg|jpeg|gif|svg|ico|css|woff|woff2|ttf|eot|mp4|webm)(\?|/|$)',
    re.IGNORECASE
)


def parse_recon_output(raw_stdout: str) -> list[str]:
    """
    Parse recon.sh stdout into a deduplicated list of valid subdomain hostnames.
    Input:  raw stdout string (one subdomain per line)
    Output: list[str] — each item is a valid subdomain hostname
    """
    seen = set()
    results = []

    for line in raw_stdout.splitlines():
        hostname = line.strip().lower()
        if not hostname:
            continue
        # Skip log/status lines from recon.sh
        if hostname.startswith("[") or hostname.startswith("#"):
            continue
        # Validate hostname format
        if len(hostname) > 253:
            continue
        if not _HOSTNAME_RE.match(hostname):
            continue
        if hostname not in seen:
            seen.add(hostname)
            results.append(hostname)

    return results


def parse_archived_urls(raw_content: str) -> dict[str, list[str]]:
    """
    Parse archived full URLs from GAU/Waymore into {hostname: ["/path?query", ...]}.
    Keeps query parameters, strips fragments, filters static assets and root paths.
    """
    host_paths: dict[str, set[str]] = {}

    for line in raw_content.splitlines():
        url = line.strip()
        if not url:
            continue
        try:
            parsed = urlparse(url)
        except Exception:
            continue

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            continue

        path = parsed.path or "/"
        if parsed.query:
            path = path + "?" + parsed.query

        if path in ("/", ""):
            continue

        if _STATIC_PATTERN.search(path):
            continue

        host_paths.setdefault(hostname, set()).add(path)

    return {
        host: sorted(paths, key=str.lower)
        for host, paths in host_paths.items()
    }
