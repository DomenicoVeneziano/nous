# engine/parsers/crawler_parser.py
import re

_DOMAIN_RE = re.compile(r'^//([a-zA-Z0-9][a-zA-Z0-9.\-]+)$')


def parse_crawler_output(crawl_file_content: str) -> dict:
    """
    Parse crawler.py output into subdomains and endpoints.
    Input:  content of <asset_hash>_crawl.txt
    Output: {subdomains: list[str], endpoints: list[str]}
    """
    subdomains = []
    endpoints = []
    seen_subs = set()
    seen_endpoints = set()

    for line in crawl_file_content.splitlines():
        line = line.strip()
        if not line:
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
    }
