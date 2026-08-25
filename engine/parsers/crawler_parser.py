# engine/parsers/crawler_parser.py
import re

_DOMAIN_RE = re.compile(r'^//([a-zA-Z0-9][a-zA-Z0-9.\-]+)$')
_STATUS_RE = re.compile(r'^#status\s+(none|\d+)$')
_REDIRECT_RE = re.compile(r'^#redirect\s+([a-zA-Z0-9._\-]+)$')
# Written when the start URL redirected to a host that cannot be named (an IPv6
# literal, or anything outside the charset above). It carries no argument on
# purpose, so it can never be confused with a real host called "unknown".
_REDIRECT_UNKNOWN = '#redirect-unknown'


def parse_crawler_output(crawl_file_content: str) -> dict:
    """
    Parse crawler.py output into subdomains, endpoints, and start-URL markers.
    Input:  content of <asset_hash>_crawl.txt
    Output: {subdomains: list[str], endpoints: list[str], status: int | None,
             redirect_to: str | None, redirected: bool}

    "redirected" and "redirect_to" are separate on purpose: a redirect whose
    destination is not representable as a host name still sets redirected=True
    with redirect_to=None, so suppression and retry decisions stay correct even
    when there is no host to follow up on.

    Parsing is lossless: endpoints are returned even when redirected is set, so
    a partially written file stays diagnosable. Acting on a redirect (suppressing
    the endpoints) is the caller's decision.
    """
    subdomains = []
    endpoints = []
    seen_subs = set()
    seen_endpoints = set()
    status = None
    redirect_to = None
    redirected = False

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
            # Markers may appear in either order; each line matches at most one.
            redirect_match = _REDIRECT_RE.match(line)
            if redirect_match:
                redirect_to = redirect_match.group(1).lower()
                redirected = True
                continue
            if line == _REDIRECT_UNKNOWN:
                redirected = True
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
        "redirect_to": redirect_to,
        "redirected": redirected,
    }
