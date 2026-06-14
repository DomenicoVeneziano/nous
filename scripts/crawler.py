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

    @crawler.pre_navigation_hook
    async def setup_network_interceptor(context: PlaywrightPreNavCrawlingContext) -> None:
        current_url = context.request.url
        page_network_paths[current_url] = set()

        async def handle_response(response):
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
                            urls_to_queue.append(absolute_url)
                    except (ValueError, TypeError):
                        pass

            if urls_to_queue:
                await context.add_requests(urls_to_queue)
        except Exception:
            pass

    # Run the crawler silently
    await crawler.run([start_url])

    # --- FINAL CLEAN OUTPUT LOGIC ---
    sorted_paths = sorted(list(GLOBAL_DISCOVERED_PATHS))

    if output_file:
        with open(output_file, 'w') as f:
            for path in sorted_paths:
                f.write(f"{path}\n")
    else:
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
