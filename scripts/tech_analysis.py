import asyncio
import argparse
import json
import re
import os
import signal
import sys
import time
import logging
import urllib.error
import urllib.request
from datetime import timedelta
from urllib.parse import urlparse, unquote

# Forcefully suppress all logs, tracebacks, and warnings as required.
# NOTE: do NOT set sys.tracebacklimit = 0 here. Combined with the asyncio /
# Playwright shutdown path, it turns an ordinary per-host failure (e.g. a TLS
# handshake error on one target) into a process-level exit(1), which aborts the
# whole batch and marks every remaining asset as SCAN_ERROR. stderr is already
# routed to /dev/null below, so tracebacks stay out of the output regardless.
os.environ['CRAWLEE_LOG_LEVEL'] = 'CRITICAL'
logging.disable(logging.CRITICAL)
import warnings
warnings.filterwarnings("ignore")
sys.stderr = open(os.devnull, 'w')

from camoufox import AsyncNewBrowser
from typing_extensions import override
from crawlee.browsers import (
    BrowserPool,
    PlaywrightBrowserController,
    PlaywrightBrowserPlugin,
)
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.storage_clients import MemoryStorageClient


class WappalyzerEngine:
    """Embedded Wappalyzer evaluation engine."""
    def __init__(self):
        self.rules = {}
        self.js_keys = set()
        self._load_technologies()

    def _load_technologies(self):
        url = "https://raw.githubusercontent.com/s0md3v/wappalyzer-next/refs/heads/main/wappalyzer/data/technologies.json"
        cache_path = os.path.join(os.environ.get("DATA_DIR", "./data"), "wappalyzer", "technologies.json")
        cache_ttl_seconds = int(os.environ.get("WAPPALYZER_CACHE_TTL_HOURS", "720")) * 3600

        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        if os.path.isfile(cache_path) and (time.time() - os.path.getmtime(cache_path)) < cache_ttl_seconds:
            with open(cache_path, "r", encoding="utf-8") as f:
                tech_data = json.load(f)
        else:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    raw = response.read().decode('utf-8')
                tech_data = json.loads(raw)
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(raw)
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                # Remote fetch failed — fall back to stale cache if available
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        tech_data = json.load(f)
                except FileNotFoundError:
                    raise RuntimeError(
                        f"Failed to download technologies.json and no local cache exists at {cache_path}"
                    )
        
        for tech, data in tech_data.items():
            self.rules[tech] = {
                'headers': {},
                'cookies': {},
                'meta': {},
                'html': self._get_compiled(data.get('html', [])),
                'scriptSrc': self._get_compiled(data.get('scriptSrc', [])),
                'js': {}
            }
            for k, v in data.get('headers', {}).items():
                self.rules[tech]['headers'][k.lower()] = self._get_compiled(v)
            for k, v in data.get('cookies', {}).items():
                self.rules[tech]['cookies'][k.lower()] = self._get_compiled(v)
            for k, v in data.get('meta', {}).items():
                self.rules[tech]['meta'][k.lower()] = self._get_compiled(v)
            for k, v in data.get('js', {}).items():
                self.rules[tech]['js'][k] = self._get_compiled(v)
                self.js_keys.add(k)

    def _get_compiled(self, patterns):
        if isinstance(patterns, str):
            patterns = [patterns]
        elif isinstance(patterns, dict):
            patterns = list(patterns.values())
        
        res = []
        for p in patterns:
            if not isinstance(p, str): continue
            # Strip custom Wappalyzer versioning syntax e.g., "\;version:\1"
            clean_p = p.split('\\;')[0]
            try:
                res.append(re.compile(clean_p, re.IGNORECASE))
            except re.error:
                continue
        return res

    def analyze(self, html, headers, cookies, scripts, meta, js_data):
        detected = set()
        headers_lower = {k.lower(): str(v) for k, v in headers.items()}
        cookies_lower = {k.lower(): str(v) for k, v in cookies.items()}
        meta_lower = {k.lower(): str(v) for k, v in meta.items()}

        for tech, rules in self.rules.items():
            # Match HTML
            if any(r.search(html) for r in rules['html']):
                detected.add(tech); continue
            
            # Match Script Src
            if any(r.search(src) for src in scripts for r in rules['scriptSrc']):
                detected.add(tech); continue
            
            # Match Headers
            if any(h_name in headers_lower and any(r.search(headers_lower[h_name]) for r in h_rules) 
                   for h_name, h_rules in rules['headers'].items()):
                detected.add(tech); continue

            # Match Cookies
            if any(c_name in cookies_lower and any(r.search(cookies_lower[c_name]) for r in c_rules) 
                   for c_name, c_rules in rules['cookies'].items()):
                detected.add(tech); continue

            # Match Meta
            if any(m_name in meta_lower and any(r.search(meta_lower[m_name]) for r in m_rules) 
                   for m_name, m_rules in rules['meta'].items()):
                detected.add(tech); continue

            # Match JS
            for j_name, j_rules in rules['js'].items():
                if j_name in js_data:
                    val = str(js_data[j_name])
                    if not j_rules or any(r.search(val) for r in j_rules):
                        detected.add(tech); break

        return list(detected)


class CamoufoxPlugin(PlaywrightBrowserPlugin):
    """Browser plugin that uses the stealth Camoufox browser."""
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


async def _initial_redirect_status(response):
    """Return the HTTP status of the first hop in a redirect chain (e.g. 301),
    walking back from the final response, or None if there was no redirect."""
    try:
        if response is None:
            return None
        prev = response.request.redirected_from
        if prev is None:
            return None
        while prev.redirected_from is not None:
            prev = prev.redirected_from
        origin_response = await prev.response()
        return origin_response.status if origin_response else None
    except Exception:
        return None


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


async def main() -> None:
    parser = argparse.ArgumentParser(description="Camoufox Tech Fingerprinter")
    parser.add_argument('urls', nargs='*', help="List of URLs or a text file containing URLs")
    parser.add_argument('-o', '--output', type=str, help="Optional flag to output results to a specific text file")
    parser.add_argument('-f', '--folder', type=str, help="Optional flag to save a raw dump (Headers, HTML, Status) of the visits")
    parser.add_argument('-s', '--screenshot-dir', type=str, default=None, help="Optional directory to save a screenshot (<domain>.png) of each page after it loads")
    parser.add_argument('--delay', type=float, default=0, help="Seconds to wait between requests")
    parser.add_argument('--proxy', type=str, default=None, help="Proxy URL (scheme://[user:pass@]host:port) to route browser traffic through")
    args = parser.parse_args()

    proxy_options = build_proxy_options(args.proxy)

    # Parse URLs from args or file and auto-fix missing protocols
    raw_urls = []
    for u in args.urls:
        if os.path.isfile(u):
            with open(u, 'r', encoding='utf-8') as f:
                raw_urls.extend([line.strip() for line in f if line.strip()])
        else:
            raw_urls.append(u)

    target_urls = []
    for url in raw_urls:
        parsed = urlparse(url)
        if not parsed.scheme:
            target_urls.append(f"http://{url}")
        else:
            target_urls.append(url)

    if not target_urls:
        return

    if args.folder:
        os.makedirs(args.folder, exist_ok=True)

    if args.screenshot_dir:
        os.makedirs(args.screenshot_dir, exist_ok=True)

    wapp_engine = WappalyzerEngine()
    js_eval_script = """
    (keys) => {
        let res = {};
        for(let key of keys) {
            try {
                let parts = key.split('.');
                let val = window;
                for(let p of parts) {
                    if (val === null || val === undefined) break;
                    val = val[p];
                }
                if (val !== undefined && val !== null) res[key] = String(val);
            } catch(e) {}
        }
        return res;
    }
    """

    nav_timeout = int(os.environ.get("TECH_NAV_TIMEOUT", "30"))
    browser_launch_options = {"proxy": proxy_options} if proxy_options else {}
    crawler = PlaywrightCrawler(
        max_requests_per_crawl=len(target_urls),
        browser_pool=BrowserPool(plugins=[CamoufoxPlugin(
            browser_launch_options=browser_launch_options,
            browser_new_context_options={"ignore_https_errors": True},
        )]),
        storage_client=MemoryStorageClient(),  # Prevents the on-disk storage folder creation
        ignore_http_error_status_codes=list(range(400, 600)),
        request_handler_timeout=timedelta(seconds=nav_timeout),
    )

    first_request = True

    @crawler.router.default_handler
    async def request_handler(context: PlaywrightCrawlingContext) -> None:
        nonlocal first_request
        if args.delay > 0 and not first_request:
            await asyncio.sleep(args.delay)
        first_request = False
        try:
            url = context.request.url
            domain = urlparse(url).netloc

            # Extract standard page properties
            response = context.response
            status_code = response.status if response else 0
            headers = response.headers if response else {}

            # Cross-host redirect handling: if the asset redirected to a
            # different host, record the redirect itself (the originating 3xx
            # status + the destination host) rather than the destination page's
            # title/tech/screenshot, which would misrepresent the asset. The
            # destination is reported via a 6th [redirects_to] field; the engine
            # decides whether to add it as an in-scope asset and scan it.
            req_host = urlparse(url).hostname
            final_host = urlparse(context.page.url).hostname
            if final_host and req_host and final_host != req_host:
                redirect_status = await _initial_redirect_status(response)
                if redirect_status is None:
                    redirect_status = status_code
                out_str = f"[{domain}][{redirect_status}][][][][{final_host}]"
                if args.output:
                    with open(args.output, 'a', encoding='utf-8') as f:
                        f.write(out_str + '\n')
                else:
                    sys.__stdout__.write(out_str + '\n')
                    sys.__stdout__.flush()
                return  # no tech extraction, dump, or screenshot for redirects

            title = await context.page.title()
            html = await context.page.content()
            
            content_length = headers.get('content-length', '0')
            if content_length == '0':
                content_length = str(len(html.encode('utf-8')))

            # Extract deeply nested DOM / network characteristics
            cookies_list = await context.page.context.cookies()
            cookies = {c['name']: c['value'] for c in cookies_list}
            scripts = await context.page.evaluate("Array.from(document.scripts).map(s => s.src)")
            meta = await context.page.evaluate("Array.from(document.querySelectorAll('meta')).reduce((acc, el) => { if(el.name || el.property) acc[el.name || el.property] = el.content; return acc; }, {})")
            js_data = await context.page.evaluate(js_eval_script, list(wapp_engine.js_keys))

            # Trigger the Wappalyzer detection logic
            detected_tech = wapp_engine.analyze(html, headers, cookies, scripts, meta, js_data)
            tech_string = ", ".join(sorted(detected_tech))

            # Strict formatting output (trailing [] = no cross-host redirect)
            out_str = f"[{domain}][{status_code}][{title}][{content_length}][{tech_string}][]"

            if args.output:
                with open(args.output, 'a', encoding='utf-8') as f:
                    f.write(out_str + '\n')
            else:
                sys.__stdout__.write(out_str + '\n')
                sys.__stdout__.flush()

            # Handle raw dump request
            if args.folder:
                safe_domain = domain.replace('.', '_')
                dump_path = os.path.join(args.folder, f"{safe_domain}.txt")
                with open(dump_path, 'w', encoding='utf-8') as df:
                    df.write(f"Status Code: {status_code}\n")
                    df.write("Headers:\n")
                    for k, v in headers.items():
                        df.write(f"  {k}: {v}\n")
                    df.write("\nHTML Content:\n")
                    df.write(html)

            # Capture a screenshot once the page has fully loaded. Isolated in its
            # own try/except so a capture failure never aborts the analysis of
            # this (or any other) asset. Writing to a fixed <domain>.png path
            # overwrites any previous screenshot, keeping only the latest.
            # Cross-host redirects already returned early above, so any page
            # reaching here represents the asset itself and is safe to capture.
            if args.screenshot_dir:
                safe_domain = domain.replace('.', '_')
                shot_path = os.path.join(args.screenshot_dir, f"{safe_domain}.png")
                try:
                    try:
                        await context.page.wait_for_load_state('load', timeout=15000)
                    except Exception:
                        pass  # proceed with whatever has rendered so far
                    await context.page.screenshot(path=shot_path, full_page=False)
                except Exception as se:
                    sys.__stdout__.write(f"[screenshot-error][{domain}] {se}\n")
                    sys.__stdout__.flush()

        except Exception:
            # Complete suppression of any runtime or handling errors
            pass

    await crawler.run(target_urls)

if __name__ == '__main__':
    async def _main():
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
        try:
            await main()
        except asyncio.CancelledError:
            pass

    asyncio.run(_main())