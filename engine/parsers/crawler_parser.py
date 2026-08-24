# engine/parsers/crawler_parser.py
import re

_DOMAIN_RE = re.compile(r'^//([a-zA-Z0-9][a-zA-Z0-9.\-]+)$')
_STATUS_RE = re.compile(r'^#status\s+(none|\d+)$')


def parse_crawler_output(crawl_file_content: str) -> dict:
    """
    Parse crawler.py output into subdomains, endpoints, and start-URL status.
    Input:  content of <asset_hash>_crawl.txt
    Output: {subdomains: list[str], endpoints: list[str], status: int | None}
    """
    subdomains = []
    endpoints = []
    seen_subs = set()
    seen_endpoints = set()
    status = None

    for line in crawl_file_content.splitlines():
        line = line.strip()
        if not line:
            continue

        # Marker and other comment lines start with #; never treated as paths.
        if line.startswith("#"):
            status_match = _STATUS_RE.match(line)
            if status_match:
                value = status_match.group(1)
                status = int(value) if value != "none" else None
            continue

        # Domain lines start with //
        domain_match = _DOMAIN_RE.match(line)
        if domain_match:
            sub = domain_match.group(1).lower()
            if sub not in seen_subs:
                seen_subs.add(sub)
                subdomains.append(sub)
            continue

        # Path lines start with /
        if line.startswith("/"):
            if line not in seen_endpoints:
                seen_endpoints.add(line)
                endpoints.append(line)

    return {
        "subdomains": subdomains,
        "endpoints": endpoints,
        "status": status,
    }
