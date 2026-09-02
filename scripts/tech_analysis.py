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
from urllib.parse import urlparse, unquote, urljoin

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

# Imported below the block above so its line numbering stays exactly as
# documented. Both back _png_is_uniform: PNG chunk headers and raw inflate.
import struct
import zlib

from camoufox import AsyncNewBrowser
from typing_extensions import override
from crawlee.browsers import (
    BrowserPool,
    PlaywrightBrowserController,
    PlaywrightBrowserPlugin,
)
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.storage_clients import MemoryStorageClient


# Marker prefixed to lines meant for the batch log only. engine/runner.py holds
# the same literal and routes matching lines away from the live scan UI and out
# of ScriptResult.stdout; scripts/ is not importable from the engine's import
# root, so the two copies must be kept in sync by hand. The trailing space is
# part of the prefix.
DIAG_PREFIX = "[diag] "


def diag(event: str, **kv) -> None:
    """Emit one diagnostic line: `[diag] <event> key=value ...`.

    stderr is /dev/null for the reasons documented at the top of this file, so
    this is the only sanctioned channel for anything the operator needs to see.
    Fields are never bracket-delimited, so a diagnostic can never be mistaken for
    a result line by the parser's 5-6 group regex. Values are stripped of line
    breaks and truncated so one runaway string cannot flood the log."""
    try:
        parts = [f"{DIAG_PREFIX}{event}"]
        for k, v in kv.items():
            text = str(v).replace('\r', ' ').replace('\n', ' ')
            parts.append(f"{k}={text[:200]}")
        sys.__stdout__.write(" ".join(parts) + "\n")
        sys.__stdout__.flush()
    except Exception:
        pass


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


def attach_navigation_recorder(page, on_response):
    """Report every main-frame navigation response on `page` to `on_response`
    and return a callable that detaches the listener again.

    Two callers need responses that the ordinary return value cannot give them:
    the plaintext-to-TLS retry, whose goto may raise after the navigation has
    already committed, and the pre-navigation hook, which needs the redirect
    chain of a navigation that may never reach the request handler at all.
    Callers must invoke the returned detach on every path so no listener
    accumulates on a page reused across the batch."""
    def _listener(resp) -> None:
        try:
            if resp.request.is_navigation_request() and resp.frame is page.main_frame:
                on_response(resp)
        except Exception:
            pass

    page.on('response', _listener)

    def _detach() -> None:
        try:
            page.remove_listener('response', _listener)
        except Exception:
            pass

    return _detach


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


# Ceilings for _png_is_uniform, all fixed rather than derived from the frame
# being examined. A viewport capture is far below them; anything larger is
# abstained on rather than decoded.
_PNG_MAX_DIMENSION = 20_000
_PNG_MAX_PIXELS = 64_000_000
_INFLATE_CHUNK_MAX = 1 << 20


def _png_is_uniform(png: bytes) -> bool | None:
    """True if every pixel of the frame is the same colour, False if any pixel
    provably differs, None if the frame cannot be decoded confidently.

    No image library exists in the engine image, so this reads the PNG directly.
    It never unfilters pixel by pixel in Python — orders of magnitude too slow to
    run per host. Instead it works forward by induction: filtering is a bijection
    once the row above is known, so given a previous row that is uniformly `ref`,
    a row encodes to exactly one byte sequence if it too is uniformly `ref`.
    Each row is compared against that sequence, built from the filter's real
    predictor (left / up / average / Paeth). Equality is a memcmp at C speed, and
    the first row that differs returns False immediately — that early exit is
    what keeps real content cheap.

    Shortcuts that look equivalent are not, and a wrong True deletes a good
    capture. A zero residual does not mean the pixel equals its neighbour under
    Average or Paeth, so a one-pixel vertical stripe would pass a zero-residual
    test; a solid row proves nothing about the rows around it, so bands of
    differing solid colours would pass a row-local test; and the row above row 0
    is the spec's virtual all-zero row, not `ref`, so a genuinely uniform frame
    filtered with Up or Average carries non-zero residuals there.

    Scanlines are pulled through the decompressor one at a time, and every bound
    is fixed rather than derived from the IHDR: implausible dimensions are
    rejected before any decoding, and a single inflate call is capped at
    _INFLATE_CHUNK_MAX bytes. Peak working set is therefore about one row plus
    that cap for ANY input, not just an honest one — a header claiming huge
    dimensions could otherwise make the per-call ceiling enormous and balloon the
    buffer to hundreds of MB before the raster-size limit tripped."""

    def _paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        return b if pb <= pc else c

    def _filtered_uniform_row(ft: int, value: bytes, up: bytes) -> bytes:
        """The one byte sequence a row uniformly `value` encodes to under filter
        `ft`, above a row uniformly `up`. The leading pixel differs from the rest
        because its left and upper-left neighbours are outside the image and read
        as zero."""
        lead = bytearray(bpp)
        rest = bytearray(bpp)
        for i in range(bpp):
            v, u = value[i], up[i]
            if ft == 0:
                lead[i] = rest[i] = v
            elif ft == 1:
                lead[i] = v          # left neighbour is 0 at the edge
                rest[i] = 0          # and `v` everywhere else
            elif ft == 2:
                lead[i] = rest[i] = (v - u) & 0xFF
            elif ft == 3:
                lead[i] = (v - ((0 + u) >> 1)) & 0xFF
                rest[i] = (v - ((v + u) >> 1)) & 0xFF
            else:
                lead[i] = (v - _paeth(0, u, 0)) & 0xFF
                rest[i] = (v - _paeth(v, u, u)) & 0xFF
        return bytes(lead) + bytes(rest) * (width - 1)

    def _iter_rows(views, row_size, limit):
        """Yield exactly `row_size`-byte scanlines (filter byte included) from the
        concatenated IDAT payloads, bounded output at every step."""
        dec = zlib.decompressobj()
        buf = bytearray()
        produced = 0
        # Enough to keep whole rows flowing, never more than a fixed ceiling: the
        # per-call limit must not scale with anything the file itself declares.
        chunk_max = min(row_size * 2, _INFLATE_CHUNK_MAX)
        for view in views:
            chunk = view
            while True:
                out = dec.decompress(chunk, chunk_max)
                chunk = dec.unconsumed_tail
                if out:
                    produced += len(out)
                    if produced > limit:
                        raise ValueError("raster larger than its own header claims")
                    buf += out
                    while len(buf) >= row_size:
                        yield bytes(buf[:row_size])
                        del buf[:row_size]
                if not chunk:
                    break
        out = dec.flush()
        if out:
            produced += len(out)
            if produced > limit:
                raise ValueError("raster larger than its own header claims")
            buf += out
            while len(buf) >= row_size:
                yield bytes(buf[:row_size])
                del buf[:row_size]

    try:
        if len(png) < 8 or png[:8] != b'\x89PNG\r\n\x1a\n':
            return None
        view = memoryview(png)
        pos = 8
        width = height = bit_depth = color_type = None
        compression = filter_method = interlace = None
        idat: list[memoryview] = []
        while pos + 8 <= len(png):
            (length,) = struct.unpack('>I', png[pos:pos + 4])
            ctype = png[pos + 4:pos + 8]
            data_end = pos + 8 + length
            if data_end > len(png):
                return None
            if ctype == b'IHDR':
                if length < 13:
                    return None
                (width, height, bit_depth, color_type,
                 compression, filter_method, interlace) = struct.unpack(
                    '>IIBBBBB', png[pos + 8:pos + 21])
            elif ctype == b'IDAT':
                # A frame is normally split across several IDATs; keep views, not
                # copies, so nothing is duplicated in memory.
                idat.append(view[pos + 8:data_end])
            elif ctype == b'IEND':
                break
            pos = data_end + 4  # skip the chunk CRC

        if not idat or width is None or not width or not height:
            return None
        # Guard the allocation before decoding anything: both dimensions are
        # attacker-controlled, and every buffer below is sized from them. A real
        # viewport capture is orders of magnitude under these ceilings, so an
        # image that exceeds one is not a frame this decides on.
        if (width > _PNG_MAX_DIMENSION or height > _PNG_MAX_DIMENSION
                or width * height > _PNG_MAX_PIXELS):
            return None
        # Only the two truecolour forms camoufox actually produces are decoded.
        # Palette, greyscale, 16-bit and Adam7 frames are left undecided rather
        # than guessed at — a wrong True deletes a good screenshot.
        if (bit_depth != 8 or color_type not in (2, 6)
                or interlace != 0 or compression != 0 or filter_method != 0):
            return None

        bpp = 3 if color_type == 2 else 4
        stride = width * bpp
        row_size = stride + 1

        ref = None              # the one colour the whole frame must be
        prev_val = bytes(bpp)   # the PNG spec's virtual all-zero row above row 0
        rows = 0
        # Only two distinct previous-row values ever occur (the virtual zero row,
        # then `ref`), so the expected encodings are built at most twice per
        # filter type instead of once per row.
        expected: dict[int, bytes] = {}
        for line in _iter_rows(idat, row_size, row_size * height):
            if rows >= height:
                break
            ft = line[0]
            if ft > 4:
                return None  # not a filter type this format defines
            data = line[1:]
            if ref is None:
                # Every predictor reads zero at the top-left corner, so the first
                # row's leading residual is the pixel value itself.
                ref = data[:bpp]
            if rows == 1:
                expected.clear()  # the row above is `ref` from here on
            exp = expected.get(ft)
            if exp is None:
                exp = _filtered_uniform_row(ft, ref, prev_val)
                expected[ft] = exp
            if data != exp:
                return False
            prev_val = ref
            rows += 1

        if rows != height:
            return None  # truncated raster: no verdict
        return True
    except Exception:
        # Malformed or unexpected input is undecided, never an exception: this
        # runs on the screenshot path, which must never abort an asset.
        return None


def _png_dimensions(png: bytes) -> tuple[int, int] | None:
    """Width and height straight from the PNG header, or None if it cannot be
    read.

    The captured frame is the authoritative source for these: camoufox drives a
    real window rather than an explicitly set viewport, so
    `page.viewport_size` is None in exactly the configuration production runs
    in, and the frame is in any case the thing the blank verdict actually judged.
    Frame dimensions are the calibration signal for anything viewport-related —
    the discarded byte threshold failed precisely because nobody could see them
    varying — so this reads IHDR and nothing else: no inflate, no scanlines, a
    few bytes on the blank path only."""
    try:
        if len(png) < 8 or png[:8] != b'\x89PNG\r\n\x1a\n':
            return None
        pos = 8
        while pos + 8 <= len(png):
            (length,) = struct.unpack('>I', png[pos:pos + 4])
            if png[pos + 4:pos + 8] == b'IHDR':
                if length < 8 or pos + 16 > len(png):
                    return None
                width, height = struct.unpack('>II', png[pos + 8:pos + 16])
                return (width, height) if width and height else None
            pos += 12 + length  # length + type + data + crc
        return None
    except Exception:
        return None


def _redirect_from_records(records, requested_host) -> tuple[int, str] | None:
    """First recorded 3xx whose Location resolves to a host other than
    `requested_host`, as (status, destination host), or None.

    The failed-request handler and the in-handler redirect branch need the same
    verdict from the same recorded chain, so there is one implementation."""
    for rec in records or []:
        try:
            if not (300 <= rec['status'] < 400) or not rec['location']:
                continue
            # Location may be relative; resolve it against the hop it came from.
            dest_host = urlparse(urljoin(rec['url'], rec['location'])).hostname
            if dest_host and requested_host and dest_host != requested_host:
                return rec['status'], dest_host
        except Exception:
            continue
    return None


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
            # Default to TLS: plaintext is what hosts reject with 426. The
            # engine always supplies an explicit scheme, so this only affects
            # manual CLI use.
            target_urls.append(f"https://{url}")
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

    # Seconds of the handler's own budget held back for the extraction and
    # screenshot work that must still run after a plaintext → TLS retry, so a
    # retry can never consume request_handler_timeout and cost the asset its
    # result line.
    retry_reserve_s = min(10.0, nav_timeout / 3)
    # crawlee starts counting request_handler_timeout fractionally before the
    # handler body runs; this margin keeps the final capture from racing it.
    handler_margin_s = min(1.0, nav_timeout / 10)
    # Budget for the post-load settle ladder, and what is held back from it for
    # the capture call itself.
    settle_budget_s = 12.0
    shot_reserve_s = min(5.0, nav_timeout / 6)
    # Held back from the settle budget for the in-page content assertion. The
    # ladder could otherwise spend the whole budget and leave the assertion no
    # time to run at all, so blankness was decided by budget exhaustion rather
    # than by evidence. Worst case stays inside the handler: ladder 8s +
    # assertion 4s + shot_reserve_s 5s, against a 30s nav_timeout that has
    # already navigated.
    content_reserve_s = 4.0

    browser_launch_options = {"proxy": proxy_options} if proxy_options else {}
    crawler = PlaywrightCrawler(
        max_requests_per_crawl=len(target_urls),
        # No automatic retries: a handler timeout would otherwise revisit the
        # host and emit a second line for the same domain.
        max_request_retries=0,
        browser_pool=BrowserPool(plugins=[CamoufoxPlugin(
            browser_launch_options=browser_launch_options,
            browser_new_context_options={"ignore_https_errors": True},
        )]),
        storage_client=MemoryStorageClient(),  # Prevents the on-disk storage folder creation
        ignore_http_error_status_codes=list(range(400, 600)),
        request_handler_timeout=timedelta(seconds=nav_timeout),
    )

    first_request = True

    # Navigation responses recorded per request. A navigation that never reaches
    # the request handler — a 3xx whose destination is dead fails the whole
    # navigation — would otherwise produce no line at all and be recorded as
    # SCAN_ERROR, hiding the fact that the asset itself answered. Entries are
    # added by the pre-navigation hook and popped by that request's deferred
    # cleanup, which crawlee runs after both the request handler and the
    # failed-request handler, so the dict only ever holds in-flight requests.
    nav_records: dict[str, list[dict]] = {}
    max_nav_records = 10  # bounds a redirect chain (or loop) per request
    # Request keys that already produced a line, so the normal and the failure
    # path can never both emit for the same host.
    emitted: set[str] = set()
    # Contracted markers already written, keyed (request key, kind). Deliberately
    # a separate set from `emitted`: that one guards the one-result-line-per-host
    # invariant, and a marker sharing it would consume the host's single allowed
    # result line.
    marked: set[tuple[str, str]] = set()

    def _write_out(line: str) -> None:
        if args.output:
            with open(args.output, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        else:
            sys.__stdout__.write(line + '\n')
            sys.__stdout__.flush()

    def emit_line(request_key: str, line: str) -> None:
        """Write one result line to -o (or stdout), at most once per request."""
        if request_key in emitted:
            return
        emitted.add(request_key)
        _write_out(line)
        # Mirror it into the batch log so that stays self-contained after the
        # engine unlinks the summary file.
        diag("result", line=line)

    def emit_marker(request_key: str, kind: str, line: str) -> None:
        """Write one contracted marker per request per kind, alongside the
        result lines. Markers carry three bracket groups, so the parser's
        result-line regex never matches them."""
        marker_key = (request_key, kind)
        if marker_key in marked:
            return
        marked.add(marker_key)
        _write_out(line)

    @crawler.pre_navigation_hook
    async def record_navigation(context) -> None:
        # Fully guarded: an exception raised here fails the request before it
        # ever navigates, which would cost the asset its result line. Recording
        # is an aid, never a precondition.
        detach = None
        try:
            key = context.request.unique_key
            records: list[dict] = []
            nav_records[key] = records

            def _record(resp) -> None:
                if len(records) >= max_nav_records:
                    return
                try:
                    records.append({
                        'status': resp.status,
                        'url': resp.url,
                        'location': resp.headers.get('location', ''),
                    })
                except Exception:
                    pass

            detach = attach_navigation_recorder(context.page, _record)

            async def _cleanup() -> None:
                # Runs in crawlee's finally, after both the request handler and
                # the failed-request handler, so nothing outlives its request.
                detach()
                nav_records.pop(key, None)
                emitted.discard(key)
                marked.discard((key, "shot"))

            context.register_deferred_cleanup(_cleanup)
        except Exception:
            # Leave no half-registered state behind: drop the record slot and
            # detach the listener if it was already attached.
            if detach is not None:
                detach()
            nav_records.pop(context.request.unique_key, None)

    @crawler.failed_request_handler
    async def failed_request(context, error) -> None:
        """Last chance to report a request whose navigation failed outright.

        An asset that answers with a cross-host redirect has been observed even
        when the destination never loads, so report the redirect exactly as the
        in-handler branch does — original hostname, the first cross-host 3xx
        status, destination host. Anything else stays unreported, leaving a
        genuinely unreachable host to be recorded as a failure by the engine."""
        try:
            key = context.request.unique_key
            requested_url = context.request.url
            requested_host = urlparse(requested_url).hostname
            domain = urlparse(requested_url).netloc
            hit = _redirect_from_records(nav_records.get(key), requested_host)
            if hit is not None:
                status, dest_host = hit
                emit_line(key, f"[{domain}][{status}][][][][{dest_host}]")
                return
            # Nothing redirect-shaped to report: the host itself did not answer.
            # TLS handshake failures used to vanish here without a trace.
            diag("nav-failed", domain=domain, err=f"{type(error).__name__}: {error}")
        except Exception:
            pass

    @crawler.router.default_handler
    async def request_handler(context: PlaywrightCrawlingContext) -> None:
        nonlocal first_request
        # Every wait this handler performs is measured against one deadline set
        # at entry (before the rate-limit sleep, which is charged to the same
        # request_handler_timeout), so no combination of retry and settle waits
        # can push the handler past that timeout.
        deadline = time.monotonic() + nav_timeout - handler_margin_s

        def remaining_s(reserve: float = 0.0) -> float:
            """Seconds left of the handler budget, minus a reserve for the work
            that must still follow. Never negative."""
            return max(0.0, deadline - time.monotonic() - reserve)

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

            # Plaintext rejection: a host that only serves TLS answers http://
            # with 426 (Upgrade Required), 497 (HTTP request sent to HTTPS port)
            # or a bare 400 from a TLS terminator. Retry the same host over
            # https inline and carry on extracting from the new response.
            # Inline goto rather than context.add_requests because the crawler
            # is capped at max_requests_per_crawl=len(target_urls) (a queued
            # retry would simply be dropped) and because the engine keys results
            # by netloc with last-wins — a second emitted line for the same host
            # would make the stored result order-dependent. Exactly one line per
            # host is emitted either way.
            # The engine now sends https:// whenever the TCP pre-check found 443
            # open, so this fires only when 443 looked closed (or on a terminator
            # that demands TLS on port 80) and for manual CLI runs.
            if status_code in (426, 497, 400) and url.startswith("http://"):
                https_url = "https://" + url[len("http://"):]
                retry_timeout_ms = int(remaining_s(retry_reserve_s) * 1000)
                if retry_timeout_ms > 0:
                    # A goto can raise AFTER the navigation commits (TLS done,
                    # document loading, domcontentloaded never reached). The page
                    # is then on the https document while `response` still
                    # describes the http 426 — and every extraction below reads
                    # the page. Record the main-frame navigation response as it
                    # arrives so the committed document can be reported with its
                    # own status even when the goto itself raises.
                    committed = {}
                    detach_recorder = attach_navigation_recorder(
                        context.page, lambda resp: committed.__setitem__('response', resp)
                    )
                    try:
                        retry_response = await context.page.goto(
                            https_url,
                            timeout=retry_timeout_ms,
                            wait_until='domcontentloaded',
                        )
                    except Exception:
                        retry_response = committed.get('response')
                    finally:
                        detach_recorder()

                    page_is_https = False
                    try:
                        page_is_https = context.page.url.startswith("https://")
                    except Exception:
                        pass

                    if retry_response is not None:
                        # Report the https document with a status substantiated
                        # by its own response, even if the load never finished.
                        url = https_url
                        domain = urlparse(url).netloc
                        response = retry_response
                        status_code = response.status
                        headers = response.headers
                    elif page_is_https:
                        # Committed to https with no response object to back it:
                        # nothing here can describe status and body as the same
                        # document, and an http status over an https body is a
                        # corrupt row. Abandon the asset — the engine records it
                        # as SCAN_ERROR, which is true, and no line is emitted.
                        raise RuntimeError("https retry left an unattributable document")
                    # Otherwise the navigation never committed: the page still
                    # shows the plaintext document that `response` describes.

            # Cross-host redirect handling: if the asset redirected to a
            # different host, record the redirect itself (the originating 3xx
            # status + the destination host) rather than the destination page's
            # title/tech/screenshot, which would misrepresent the asset. The
            # destination is reported via a 6th [redirects_to] field; the engine
            # decides whether to add it as an in-scope asset and scan it.
            req_host = urlparse(url).hostname
            final_host = urlparse(context.page.url).hostname
            if final_host and req_host and final_host != req_host:
                # Every rung of this ladder is substantiated by a 3xx that
                # points at THIS hop's destination. There is deliberately no
                # fallback to status_code: that is the DESTINATION page's status,
                # so the asset would be stored as the 200 of the page it landed
                # on. Nor is there a rung taking any 3xx in the chain: a host
                # that redirects to itself and only then leaves via a client-side
                # location assignment would have its own same-host 301 credited
                # to the cross-host hop. When no cross-host 3xx exists the hop
                # was client-side (a location assignment or a meta refresh) and
                # the honest answer is an empty status, which the parser turns
                # into None and the engine writes as NULL.
                key = context.request.unique_key
                redirect_status = await _initial_redirect_status(response)
                if redirect_status is None:
                    hit = _redirect_from_records(nav_records.get(key), req_host)
                    if hit is not None:
                        redirect_status = hit[0]
                if redirect_status is None:
                    diag("redirect-status-unknown", domain=domain, dest=final_host)
                status_field = '' if redirect_status is None else redirect_status
                out_str = f"[{domain}][{status_field}][][][][{final_host}]"
                emit_line(key, out_str)
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
            emit_line(context.request.unique_key, out_str)

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
                    # Settle ladder, every step capped by BOTH its own budget and
                    # what is left of the handler deadline after reserving
                    # shot_reserve_s for the capture itself — so the ladder can
                    # never eat request_handler_timeout and cost this asset its
                    # already-emitted line's screenshot. content_reserve_s is held
                    # back on top of that: the ladder could otherwise spend the
                    # whole settle budget and leave the content assertion below
                    # unable to run even once, making blankness a verdict of
                    # budget exhaustion rather than of evidence. Each step is
                    # swallowed: a step that times out just means the next one
                    # runs with less budget.
                    ladder_deadline = min(
                        time.monotonic() + settle_budget_s - content_reserve_s,
                        deadline - shot_reserve_s - content_reserve_s,
                    )

                    def ladder_left(cap: float) -> float:
                        return max(0.0, min(cap, ladder_deadline - time.monotonic()))

                    for state, cap in (('domcontentloaded', 3.0), ('networkidle', 5.0)):
                        left = ladder_left(cap)
                        if left <= 0:
                            break
                        try:
                            await context.page.wait_for_load_state(state, timeout=int(left * 1000))
                        except Exception:
                            pass  # proceed with whatever has rendered so far

                    # Assert real rendered content rather than trusting load
                    # events: an unhydrated SPA shell (<app-root></app-root>, an
                    # empty #root) and a bot-manager interstitial both answer 200
                    # over a body with nothing painted in it. The assertion gets
                    # its OWN deadline, computed here rather than shared with the
                    # ladder, so a ladder that ran long cannot zero it. The
                    # interstitial calls location.reload(), which destroys the
                    # execution context underneath the wait, so a raised error
                    # gets one more attempt against the reloaded page while budget
                    # remains.
                    content_deadline = min(
                        time.monotonic() + content_reserve_s,
                        deadline - shot_reserve_s,
                    )

                    def content_left(cap: float) -> float:
                        return max(0.0, min(cap, content_deadline - time.monotonic()))

                    content_ok = False
                    for _ in range(2):
                        left = content_left(3.0)
                        if left <= 0:
                            break
                        try:
                            await context.page.wait_for_function(
                                "document.body && (document.body.innerText.trim().length > 0 "
                                "|| document.querySelector('img,svg,canvas,video,input,button,iframe'))",
                                timeout=int(left * 1000),
                            )
                            content_ok = True
                            break
                        except Exception:
                            continue

                    # Only when the cheap polled predicate has given up: one
                    # evaluate that also looks for CSS background imagery, which
                    # a page can be painted entirely with. It doubles as the DOM
                    # snapshot the blank diagnostic reports, and every field is
                    # read under its own guard so one unreadable value never
                    # costs the others.
                    #
                    # Page.evaluate takes no timeout of its own and is not
                    # governed by the default action timeout: it blocks until the
                    # page's execution context answers, and the pages that reach
                    # here are exactly the ones whose main thread is busy. The
                    # bound has to be imposed from outside, or this one await
                    # escapes the handler deadline and crawlee cancels the
                    # request — a cancel skips the except below, so the host
                    # would lose its screenshot AND its marker.
                    dom_info = {}
                    ev_budget = min(2.0, remaining_s(shot_reserve_s))
                    if not content_ok and ev_budget > 0:
                        try:
                            dom_info = await asyncio.wait_for(
                                context.page.evaluate("""() => {
                                    const out = {};
                                    try {
                                        out.bg = Array.from(document.querySelectorAll('body *'))
                                            .slice(0, 300)
                                            .some(el => {
                                                const b = getComputedStyle(el).backgroundImage;
                                                return b && b !== 'none';
                                            });
                                    } catch (e) {}
                                    try { out.body_len = document.body ? document.body.innerText.trim().length : -1; } catch (e) {}
                                    try { out.nodes = document.getElementsByTagName('*').length; } catch (e) {}
                                    try { out.ready = document.readyState; } catch (e) {}
                                    try { out.url = location.href; } catch (e) {}
                                    return out;
                                }"""),
                                timeout=ev_budget,
                            ) or {}
                        except Exception:
                            # Including the timeout: losing the background-image
                            # promotion in that tail is far cheaper than losing
                            # the handler.
                            dom_info = {}

                    if dom_info.get('bg'):
                        content_ok = True

                    # Capture to a buffer so a blank frame can be rejected before
                    # it reaches disk. There is deliberately no size threshold in
                    # the verdict: measured across camoufox's randomised
                    # viewports, solid-colour frames encode to 5–16 KB while real
                    # content can encode smaller, so the two distributions overlap
                    # and no byte floor can separate them. The frame's own pixels
                    # decide instead, with the DOM assertion catching the
                    # near-blank shell that painted a single header bar.
                    shot_budget_ms = int(remaining_s() * 1000)
                    if shot_budget_ms <= 0:
                        raise TimeoutError("handler budget exhausted before capture")
                    png = await context.page.screenshot(
                        full_page=False, timeout=shot_budget_ms
                    )
                    # A provably single-colour frame is worthless whatever the DOM
                    # claimed — it means the capture caught the page mid-paint or
                    # behind an unpainted layer, so pixels win. An undecodable
                    # frame leaves the assertion as the only signal.
                    uniform = _png_is_uniform(png)
                    if uniform is True or not content_ok:
                        # Removing any previous image is what lets the engine's
                        # mtime freshness test see "no image from this run".
                        try:
                            os.unlink(shot_path)
                        except OSError:
                            pass
                        size = _png_dimensions(png)
                        frame = f"{size[0]}x{size[1]}" if size else ''
                        diag(
                            "screenshot-blank",
                            domain=domain,
                            # Reported for observability only; no branch reads it.
                            bytes=len(png),
                            frame=frame,
                            content_ok=1 if content_ok else 0,
                            uniform='unknown' if uniform is None else (1 if uniform else 0),
                            # The signals disagreeing is a population worth
                            # watching, so it is flagged rather than inferred.
                            disagree=1 if (uniform is True and content_ok) else 0,
                            body_len=dom_info.get('body_len', ''),
                            nodes=dom_info.get('nodes', ''),
                            ready=dom_info.get('ready', ''),
                            url=dom_info.get('url', ''),
                        )
                        emit_marker(context.request.unique_key, "shot", f"[shot][{domain}][blank]")
                    else:
                        with open(shot_path, 'wb') as sf:
                            sf.write(png)
                        emit_marker(context.request.unique_key, "shot", f"[shot][{domain}][ok]")
                except Exception as se:
                    diag("screenshot-error", domain=domain, err=f"{type(se).__name__}: {se}")
                    emit_marker(context.request.unique_key, "shot", f"[shot][{domain}][error]")

        except Exception as e:
            # Still a complete swallow: one asset failing mid-handler must never
            # take the rest of the batch with it. It only stops being silent.
            # `domain` is unbound if the failure preceded its assignment, so fall
            # back to the requested URL.
            failed_domain = ''
            try:
                failed_domain = domain
            except NameError:
                try:
                    failed_domain = context.request.url
                except Exception:
                    pass
            diag("handler-error", domain=failed_domain, err=f"{type(e).__name__}: {e}")

    await crawler.run(target_urls)

if __name__ == '__main__':
    async def _main():
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
        try:
            await main()
        except asyncio.CancelledError:
            pass

    asyncio.run(_main())