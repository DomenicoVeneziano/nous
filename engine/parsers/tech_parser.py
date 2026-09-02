# engine/parsers/tech_parser.py
import re

# Matches: [domain][status_code][title][content_length][tech1,tech2,...][redirects_to?]
# The trailing [redirects_to] field is optional for backward compatibility; it is
# populated (with the destination host) only for cross-host redirects.
_LINE_RE = re.compile(
    r'^\[([^\]]*)\]\[([^\]]*)\]\[([^\]]*)\]\[([^\]]*)\]\[([^\]]*)\](?:\[([^\]]*)\])?$'
)

# Matches: [shot][domain][ok|blank|error]
# Screenshot markers carry three bracket groups, so they never match _LINE_RE.
_SHOT_RE = re.compile(r'^\[shot\]\[([^\]]*)\]\[([^\]]*)\]$')

_SHOT_VERDICTS = ("ok", "blank", "error")


def parse_tech_output(summary_log_content: str) -> list[dict]:
    """
    Parse tech_analysis.py summary log into structured records.
    Input:  content of summary.log file
    Output: list[dict] with keys: domain, status_code, title, content_length, technologies
    """
    results = []

    for line in summary_log_content.splitlines():
        line = line.strip()
        if not line:
            continue

        match = _LINE_RE.match(line)
        if not match:
            continue

        domain = match.group(1).strip()
        status_raw = match.group(2).strip()
        title = match.group(3).strip() or None
        length_raw = match.group(4).strip()
        tech_raw = match.group(5).strip()

        # Parse status code
        try:
            status_code = int(status_raw) if status_raw else None
        except ValueError:
            status_code = None

        # Parse content length
        try:
            content_length = int(length_raw) if length_raw else None
        except ValueError:
            content_length = None

        # Parse technologies
        technologies = [t.strip() for t in tech_raw.split(",") if t.strip()] if tech_raw else []

        # Cross-host redirect destination (optional 6th field)
        redirects_to = (match.group(6) or "").strip() or None

        results.append({
            "domain": domain,
            "status_code": status_code,
            "title": title,
            "content_length": content_length,
            "technologies": technologies,
            "redirects_to": redirects_to,
        })

    return results


def parse_screenshot_markers(content: str) -> dict[str, str]:
    """
    Parse screenshot verdict markers out of the tech_analysis.py summary log.
    Input:  content of summary.log file
    Output: dict mapping domain -> "ok" | "blank" | "error"
    Repeated domains keep the last verdict seen; unknown verdicts are dropped.
    """
    verdicts: dict[str, str] = {}

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        match = _SHOT_RE.match(line)
        if not match:
            continue

        domain = match.group(1).strip()
        verdict = match.group(2).strip().lower()
        if not domain or verdict not in _SHOT_VERDICTS:
            continue

        verdicts[domain] = verdict

    return verdicts
