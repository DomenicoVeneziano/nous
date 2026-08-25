import argparse
import asyncio
import logging
import os
import re
import signal
import sys
from datetime import timedelta
from urllib.parse import urljoin, urlparse, unquote

# Camoufox is an external package and needs to be installed.
from camoufox import AsyncNewBrowser
from typing_extensions import override

# Mute all Crawlee and Playwright internal logging globally
logging.getLogger('crawlee').setLevel(logging.CRITICAL)
logging.getLogger('playwright').setLevel(logging.CRITICAL)

from crawlee import ConcurrencySettings
from crawlee.browsers import (
    BrowserPool,
    PlaywrightBrowserController,
    PlaywrightBrowserPlugin,
)
from crawlee.crawlers import (
    PlaywrightCrawler,
    PlaywrightCrawlingContext,
    PlaywrightPreNavCrawlingContext
)
from crawlee.crawlers._playwright._playwright_crawler import GotoOptions
from crawlee.storage_clients import MemoryStorageClient

# Global states to track paths
GLOBAL_DISCOVERED_PATHS = set()
page_network_paths = {}

# Robust regex to catch extensions even if followed by query params or trailing slashes
STATIC_PATTERN = re.compile(
    r'\.(png|jpg|jpeg|gif|svg|ico|css|woff|woff2|ttf|eot|mp4|webm)(\?|/|$)',
    re.IGNORECASE
)

# Host a "#redirect" marker is allowed to name. Mirrors the project's domain
# validator; a host that fails it cannot be named in the marker, and the run
# falls back to the argument-less "#redirect-unknown" marker instead.
_HOST_RE = re.compile(r'^[a-zA-Z0-9._\-]+$')


def _norm_host(url: str | None) -> str | None:
    """Normalise a URL's host so two URLs can be compared for "same host".

    urlparse().hostname is already lowercased and port-free, so scheme and port
    differences are ignored by construction. The single trailing root dot is
    stripped ("example.com." == "example.com") and the result is IDNA-encoded so
    a unicode host and its punycode form compare equal — both sides of every
    comparison go through this one helper. Returns None when the URL has no host
    at all (about:blank, data:, ...), which callers treat as "unknown", never as
    "different".
    """
    if not url:
        return None
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    if host.endswith("."):
        host = host[:-1]
    if not host:
        return None
    try:
        return host.encode("idna").decode("ascii").lower()
    except Exception:
        return host.lower()


class CamoufoxPlugin(PlaywrightBrowserPlugin):
    """Example browser plugin that uses Camoufox browser,
    but otherwise keeps the functionality of PlaywrightBrowserPlugin.
    """
    @override
    async def new_browser(self) -> PlaywrightBrowserController:
        if not self._playwright:
            raise RuntimeError('Playwright browser plugin is not initialized.')

        return PlaywrightBrowserController(
            browser=await AsyncNewBrowser(
                self._playwright, **self._browser_launch_options
            ),
            max_open_pages_per_browser=1,
            header_generator=None,
        )

def build_proxy_options(proxy_url: str | None) -> dict | None:
    """Parse a proxy URL (scheme://[user:pass@]host:port) into Playwright proxy options."""
    if not proxy_url:
        return None
    p = urlparse(proxy_url)
    if not p.hostname:
        return None
    server = f"{p.scheme}://{p.hostname}:{p.port}" if p.port else f"{p.scheme}://{p.hostname}"
    opts = {"server": server}
    if p.username:
        opts["username"] = unquote(p.username)
    if p.password:
        opts["password"] = unquote(p.password)
    return opts


# URL-path validator (mirrored in PATH_EXTRACTION_JS). Inline <script> bodies
# contain JavaScript whose "/..." fragments (regex literals, division, object
# code) would otherwise be scraped as bogus paths — e.g. "/&&a.target",
# "/,a.innerHTML=", "/*/*". A real path:
#   * starts with "/" (root "/" and "/?query" are allowed),
#   * if it has a path segment, that segment starts with an unreserved-ish char
#     (rejecting operator/punctuation-led JS like "/,", "/&&", "/*", "/["),
#   * uses the RFC 3986 "pchar" set for the path, so meaningful paths survive:
#     /_next/..., /.well-known/..., /@scope, /wiki/Foo_(bar), /v1/users:batchGet.
# JS-operator sequences are rejected only in the PATH portion; the query and
# fragment stay permissive so //-URLs, base64 "==" padding, etc. are kept.
_PATH_RE = re.compile(
    r"^/(?:[A-Za-z0-9._~@\-][A-Za-z0-9._~%!$&'()*+,;=:@/\-]*)?"
    r"(?:\?[^\s'\"<>]*)?(?:#[^\s'\"<>]*)?$"
)
_NOISE_SEQ = ("//", "..", "/*", "*/", "&&", "||", "==", "=>", "++", "--", "::", "=<", "><")


def _is_valid_path(p: str) -> bool:
    if not p or len(p) > 512 or not p.startswith("/"):
        return False
    path_part = re.split(r"[?#]", p, 1)[0]
    if any(seq in path_part for seq in _NOISE_SEQ):
        return False
    return bool(_PATH_RE.match(p))


def extract_paths_python(text: str) -> set:
    """Extract realistic URL paths from a network response body.

    Patterns capture broadly (HTML attributes + quoted absolute paths referenced
    from JS); _is_valid_path is the single gate that separates real paths from
    scraped JavaScript noise.
    """
    if not text:
        return set()

    patterns = [
        r"href=['\"](/[^'\"]*)['\"]",
        r"src=['\"](/[^'\"]*)['\"]",
        r"action=['\"](/[^'\"]*)['\"]",
        r"url\(['\"]?(/[^'\")]*)['\"]?\)",
        r"['\"`](/[A-Za-z0-9._~@\-][^'\"`\s]*)['\"`]",
    ]

    found = set()
    for pattern in patterns:
        for match in re.findall(pattern, text):
            clean_path = match.strip("'\"`")
            if _is_valid_path(clean_path):
                found.add(clean_path)
    return found

# Lightweight JS payload: ONLY scans the rendered frontend DOM.
PATH_EXTRACTION_JS = """
async () => {
    let paths = new Set();

    // Mirror of _is_valid_path: keep real paths, drop JS fragments scraped from
    // inline <script> bodies. JS-operator sequences are rejected only in the
    // path portion; query/fragment stay permissive (//-URLs, base64 ==, etc.).
    const PATH_RE = /^\\/(?:[A-Za-z0-9._~@\\-][A-Za-z0-9._~%!$&'()*+,;=:@\\/\\-]*)?(?:\\?[^\\s'"<>]*)?(?:#[^\\s'"<>]*)?$/;
    const NOISE = ["//", "..", "/*", "*/", "&&", "||", "==", "=>", "++", "--", "::", "=<", "><"];
    const isValidPath = (p) => {
        if (!p || p.length > 512 || p[0] !== '/') return false;
        const pathPart = p.split(/[?#]/)[0];
        for (const s of NOISE) if (pathPart.indexOf(s) !== -1) return false;
        return PATH_RE.test(p);
    };

    const extractPaths = (text) => {
        if (!text) return [];
        const patterns = [
            /(?<=href=['"])\\/[^'"]*(?=['"])/g,
            /(?<=src=['"])\\/[^'"]*(?=['"])/g,
            /(?<=action=['"])\\/[^'"]*(?=['"])/g,
            /(?<=url\\(['"]?)\\/[^'")]*(?=['"]?\\))/g,
            /(?<=['"`])\\/[A-Za-z0-9._~@\\-][^'"`\\s]*(?=['"`])/g
        ];
        let found = [];
        patterns.forEach(pattern => {
            try {
                [...text.matchAll(pattern)].forEach(m => { if (isValidPath(m[0])) found.push(m[0]); });
            } catch(e) {}
        });
        return found;
    };

    extractPaths(document.documentElement.outerHTML).forEach(p => paths.add(p));

    document.querySelectorAll('script:not([src])').forEach(s => {
        extractPaths(s.textContent).forEach(p => paths.add(p));
    });

    // Real loaded resources are reliable; keep same-origin path + query.
    if (window.performance && performance.getEntriesByType) {
        performance.getEntriesByType('resource').forEach(r => {
            if (!r.name) return;
            try {
                const u = new URL(r.name, location.href);
                if (u.origin === location.origin) {
                    const pth = u.pathname + u.search;
                    if (isValidPath(pth)) paths.add(pth);
                }
            } catch(e) {}
        });
    }

    return Array.from(paths);
}
"""

async def run_crawler(start_url: str, max_pages: int, output_file: str, delay: float = 0,
                      proxy_url: str | None = None) -> None:
    # Forcefully mute any unretrieved asyncio Future exceptions from Playwright
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda l, c: None)

    proxy_options = build_proxy_options(proxy_url)
    browser_launch_options = {"proxy": proxy_options} if proxy_options else {}

    nav_timeout = int(os.environ.get("CRAWL_NAV_TIMEOUT", "60"))
    crawler = PlaywrightCrawler(
        max_requests_per_crawl=max_pages,
        browser_pool=BrowserPool(plugins=[CamoufoxPlugin(
            browser_launch_options=browser_launch_options,
            browser_new_context_options={"ignore_https_errors": True},
        )]),
        max_request_retries=0,
        storage_client=MemoryStorageClient(),  # <--- Forces in-memory storage, no disk folder
        ignore_http_error_status_codes=list(range(400, 600)),
        goto_options=GotoOptions(wait_until="networkidle"),
        request_handler_timeout=timedelta(seconds=nav_timeout),
        concurrency_settings=ConcurrencySettings(max_concurrency=1) if delay > 0 else None,
    )

    # HTTP status the crawler was actually served for the start URL. Persisted to
    # the output file as a "#status <code>" marker line so a caller can tell a
    # block (e.g. 403 from a WAF) apart from an empty page that returned 200 with
    # no links. "final" flips once the end-of-run write owns the file.
    start_status = {"code": None, "final": False}
    # The first navigation and the first handled request belong to the start URL;
    # comparing URLs alone is not enough because the crawler may normalise them.
    seen_navigation = {"hook": False, "handler": False}

    # Host the crawl is scoped to. None (a start URL with no host) disables the
    # redirect logic entirely, degrading to the previous behaviour rather than
    # suppressing everything.
    start_host = _norm_host(start_url)
    # Redirect bookkeeping for the start navigation, deliberately split in two
    # because the two decisions it drives have different requirements and MUST
    # NOT be merged back into a single value:
    #   * "redirected" — the start URL ended up on a host other than start_host.
    #     True regardless of whether that host can be named, because it is what
    #     suppresses the run's paths: a redirected start URL harvests the OTHER
    #     host's paths, so they may never be attributed to this one.
    #   * "redirect_to" — the destination host, set ONLY when _HOST_RE accepts
    #     it, because it is what a caller follows up on and an unvalidated,
    #     response-header-controlled value may not be handed onward.
    # Deriving both from one value is exactly the bug this split fixes: an
    # attacker-controlled Location naming an IPv6 literal (or any host outside
    # the charset) suppressed every path while writing no marker at all, leaving
    # the host recorded as "crawled, 0 endpoints" with nothing to retry or
    # follow. Persisted as "#redirect <host>" / "#redirect-unknown" marker lines
    # so a caller can tell "this host redirects elsewhere" apart from "this host
    # has nothing to crawl".
    redirect_state = {"redirected": False, "redirect_to": None}

    def _marker_lines(final: bool = False) -> list[str]:
        lines = []
        code = start_status["code"]
        if code is not None:
            lines.append(f"#status {code}")
        elif final:
            # The end-of-run write has always emitted an explicit "#status none"
            # so a complete file is never ambiguous; checkpoint writes omit the
            # line instead, because the status may still arrive.
            lines.append("#status none")
        if redirect_state["redirect_to"]:
            lines.append(f"#redirect {redirect_state['redirect_to']}")
        elif redirect_state["redirected"]:
            # Redirected, but the destination is not representable as a host
            # name. The marker carries no argument on purpose: any placeholder
            # word would collide with a real host that could be named the same.
            lines.append("#redirect-unknown")
        return lines

    def persist_markers() -> None:
        """Write the marker block as soon as any of it is known.

        The run can be cancelled or time out before the end-of-run write, so the
        markers are checkpointed here instead of only at the end. The file is
        (re)written with the markers alone; the end-of-run write rewrites them
        followed by the discovered paths.
        """
        if start_status["final"] or not output_file:
            return
        lines = _marker_lines()
        if not lines:
            # Nothing is known yet, so there is nothing to checkpoint. Returning
            # before open() matters: opening for write would truncate whatever
            # was already checkpointed to zero bytes, and a run killed at that
            # moment leaves a file that reads back as "no status" and triggers a
            # full re-crawl the previous content would have suppressed.
            return
        try:
            with open(output_file, 'w') as f:
                for line in lines:
                    f.write(f"{line}\n")
        except OSError:
            pass

    def record_redirect(host: str | None) -> None:
        """Record the host the start navigation currently sits on.

        Every hop OVERWRITES the destination instead of latching the first
        offsite one: a chain that leaves the start host and comes back
        (a -> b -> a) has to end up as "not a redirect", so only the last hop
        counts. A host equal to the start host clears BOTH pieces of state
        again.

        A host that _HOST_RE rejects still counts as redirected; it just cannot
        be named, so redirect_to stays None while redirected goes True.
        """
        if start_host is None:
            return
        offsite = host is not None and host != start_host
        dest = host if (offsite and _HOST_RE.match(host)) else None
        if offsite == redirect_state["redirected"] and dest == redirect_state["redirect_to"]:
            return
        redirect_state["redirected"] = offsite
        redirect_state["redirect_to"] = dest
        persist_markers()

    @crawler.pre_navigation_hook
    async def setup_network_interceptor(context: PlaywrightPreNavCrawlingContext) -> None:
        current_url = context.request.url
        page_network_paths[current_url] = set()
        is_start_navigation = not seen_navigation["hook"] or current_url == start_url
        seen_navigation["hook"] = True

        async def handle_response(response):
            if is_start_navigation and response.request.resource_type == 'document':
                # On a redirect chain every hop is a document response; the LAST
                # one is the status the crawler was actually served, which is
                # what the block/throttle decision is about, so keep overwriting.
                start_status["code"] = response.status
                persist_markers()
            if is_start_navigation and start_host is not None:
                # Fallback source for the redirect destination, so a redirect
                # whose destination fails to load is still recorded even though
                # page.url never commits to it.
                #
                # Gated on is_start_navigation, exactly like the status capture
                # above: the marker means "the START URL landed on a different
                # host". A page reached mid-crawl that redirects offsite is
                # suppressed by the handler without ever being recorded here.
                #
                # A resource_type == 'document' test alone is NOT enough here: a
                # third-party <iframe> also produces document responses, and its
                # host would then be reported as a redirect for any page that
                # embeds one. Only the main frame's own navigations may decide.
                try:
                    request = response.request
                    if (request.is_navigation_request()
                            and response.frame is context.page.main_frame):
                        location = response.headers.get("location")
                        if 300 <= response.status < 400 and location:
                            hop_host = _norm_host(urljoin(response.url, location))
                        else:
                            hop_host = _norm_host(response.url)
                        record_redirect(hop_host)
                except Exception:
                    # Never let the redirect bookkeeping break status capture or
                    # path extraction below.
                    pass
            if response.request.resource_type in ['document', 'script', 'fetch', 'xhr']:
                try:
                    text = await response.text()
                    paths = extract_paths_python(text)
                    page_network_paths[current_url].update(paths)
                except Exception:
                    pass

        context.page.on("response", handle_response)

    first_request = True

    @crawler.router.default_handler
    async def request_handler(context: PlaywrightCrawlingContext) -> None:
        nonlocal first_request
        if delay > 0 and not first_request:
            await asyncio.sleep(delay)
        first_request = False

        current_url = context.request.url

        # Fallback: if no document response was observed for the start URL, take
        # the status from the navigation response the handler was given.
        is_start_request = not seen_navigation["handler"] or current_url == start_url
        seen_navigation["handler"] = True
        if start_status["code"] is None and is_start_request:
            response = getattr(context, "response", None)
            if response is not None:
                try:
                    start_status["code"] = response.status
                    persist_markers()
                except Exception:
                    pass

        # Offsite check, deliberately placed AFTER the status capture above so
        # "#status" keeps reporting what the start URL was actually served (the
        # final code of the redirect chain); only the harvesting below is
        # skipped. page.url is the committed main-frame URL after the whole
        # chain, so this also catches JS and meta-refresh redirects. It applies
        # to every page, not just the start URL, keeping the crawl scoped to the
        # start host for the entire run.
        if start_host is not None:
            page_host = _norm_host(context.page.url)
            request_host = _norm_host(current_url)
            # ONLY the start navigation may set the "#redirect" marker: it means
            # "the START URL landed on a different host", and record_redirect
            # overwrites shared state that decides whether the run's paths are
            # written at all. A page reached mid-crawl that redirects offsite is
            # suppressed below without being recorded — never make this
            # unconditional, or one such page late in the queue discards the
            # entire legitimate crawl.
            if is_start_request and page_host is not None:
                record_redirect(page_host)
            if ((page_host is not None and page_host != start_host)
                    or (request_host is not None and request_host != start_host)):
                page_network_paths.pop(current_url, None)
                return

        try:
            network_paths = page_network_paths.pop(current_url, set())
            dom_paths = await context.page.evaluate(PATH_EXTRACTION_JS)

            all_local_paths = network_paths.union(set(dom_paths))
            GLOBAL_DISCOVERED_PATHS.update(all_local_paths)

            urls_to_queue = []
            for path in all_local_paths:
                absolute_url = urljoin(current_url, path)

                # Use regex search to filter out static media, even with query params
                if not STATIC_PATTERN.search(absolute_url):
                    # Validate URL is fully parseable before enqueueing
                    try:
                        parsed = urlparse(absolute_url)
                        if parsed.scheme in ('http', 'https') and parsed.hostname:
                            _ = parsed.port  # raises ValueError on invalid port like :blank
                            # Never queue another host: the crawl stays scoped to
                            # the start host for its whole lifetime.
                            if start_host is None or _norm_host(absolute_url) == start_host:
                                urls_to_queue.append(absolute_url)
                    except (ValueError, TypeError):
                        pass

            if urls_to_queue:
                await context.add_requests(urls_to_queue)
        except Exception:
            pass
        finally:
            # Every exit path drops the per-page entry; an exception raised
            # before the pop above would otherwise leak it for the life of the
            # process.
            page_network_paths.pop(current_url, None)

    # Run the crawler silently
    await crawler.run([start_url])

    # --- FINAL CLEAN OUTPUT LOGIC ---
    sorted_paths = sorted(list(GLOBAL_DISCOVERED_PATHS))
    marker_lines = _marker_lines(final=True)
    # A redirected start URL contributes no paths by construction; writing none
    # explicitly keeps that guarantee independent of the harvesting code.
    # Suppression follows "redirected" alone, never the destination host: a
    # destination that could not be named is still a redirect.
    redirected = redirect_state["redirected"]
    start_status["final"] = True

    if output_file:
        with open(output_file, 'w') as f:
            for line in marker_lines:
                f.write(f"{line}\n")
            if not redirected:
                for path in sorted_paths:
                    f.write(f"{path}\n")
    else:
        for line in marker_lines:
            print(line)
        if not redirected:
            for path in sorted_paths:
                print(path)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Silent Network-Intercepting Crawler")
    parser.add_argument('--start-url', type=str, required=True, help="The initial URL to crawl.")
    parser.add_argument('--max-pages', type=int, default=10, help="Maximum number of pages to crawl.")
    parser.add_argument('--delay', type=float, default=0, help="Seconds to wait between page requests (0 = no delay).")
    parser.add_argument('--proxy', type=str, default=None, help="Proxy URL (scheme://[user:pass@]host:port) to route browser traffic through.")
    parser.add_argument('-o', '--output', type=str, default=None, help="Output file to save paths (one per line).")
    args = parser.parse_args()

    # --- URL Sanitization to ensure protocol exists ---
    parsed_url = urlparse(args.start_url)
    if not parsed_url.scheme:
        start_url = f"https://{args.start_url}"
    else:
        start_url = args.start_url

    # The warning filter keeps stdout strictly clean
    import warnings
    warnings.filterwarnings("ignore")

    async def _main():
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
        try:
            await run_crawler(start_url, args.max_pages, args.output, args.delay, args.proxy)
        except asyncio.CancelledError:
            pass

    asyncio.run(_main())
