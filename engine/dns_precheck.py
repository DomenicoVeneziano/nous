# engine/dns_precheck.py
"""
DNS pre-check: resolves domains against rotating resolvers to validate
connectivity before tech analysis. IPs are passed through without lookup.
"""
import asyncio
import ipaddress
import itertools
import struct
import os
import random
from pathlib import Path
from typing import Awaitable, Callable

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
RESOLVERS_PATH = os.environ.get("RESOLVERS_PATH", str(DATA_DIR / "resolvers" / "resolvers.txt"))
DNS_TIMEOUT = float(os.environ.get("DNS_PRECHECK_TIMEOUT", "5"))
DNS_CONCURRENCY = int(os.environ.get("DNS_PRECHECK_CONCURRENCY", "50"))
DNS_RATE_LIMIT_DELAY = float(os.environ.get("DNS_RATE_LIMIT_DELAY", "0"))


def _load_resolvers(resolvers_path: str | None = None) -> list[str]:
    """Load resolver IPs from file, one per line."""
    path = Path(resolvers_path if resolvers_path is not None else RESOLVERS_PATH)
    if not path.is_file():
        return ["8.8.8.8", "1.1.1.1"]
    lines = path.read_text().strip().splitlines()
    resolvers = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    return resolvers if resolvers else ["8.8.8.8", "1.1.1.1"]


def _is_ip(value: str) -> bool:
    """Check if a string is an IP address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _build_dns_query(domain: str, qtype: int = 1) -> tuple[bytes, int]:
    """Build a raw DNS query packet. qtype: 1=A, 28=AAAA."""
    tx_id = random.randint(0, 65535)
    flags = 0x0100  # standard query, recursion desired
    header = struct.pack("!HHHHHH", tx_id, flags, 1, 0, 0, 0)
    question = b""
    for label in domain.rstrip(".").split("."):
        encoded = label.encode("ascii")
        question += struct.pack("!B", len(encoded)) + encoded
    question += b"\x00"
    question += struct.pack("!HH", qtype, 1)  # qtype, qclass=IN
    return header + question, tx_id


def _skip_name(data: bytes, offset: int) -> int:
    """Skip a DNS name at offset, return new offset after the name."""
    while offset < len(data):
        length = data[offset]
        offset += 1
        if length == 0:
            return offset
        if (length & 0xC0) == 0xC0:
            offset += 1  # pointer is 2 bytes total, already consumed 1
            return offset
        offset += length
    return offset


def _decode_name(data: bytes, offset: int) -> str:
    """Decode a DNS name from a response packet with compression support."""
    labels = []
    seen: set[int] = set()
    while offset < len(data):
        if offset in seen:
            break
        seen.add(offset)
        length = data[offset]
        if length == 0:
            break
        if (length & 0xC0) == 0xC0:
            if offset + 1 >= len(data):
                break
            pointer = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            rest = _decode_name(data, pointer)
            if rest:
                labels.append(rest)
            break
        offset += 1
        if offset + length > len(data):
            break
        labels.append(data[offset:offset + length].decode("ascii", errors="replace"))
        offset += length
    return ".".join(labels)


def _parse_rr(data: bytes, rtype: int, rdata_start: int, rdlength: int) -> dict | None:
    """Parse a single DNS resource record into a dict. Returns None for unrecognised types."""
    rdata = data[rdata_start:rdata_start + rdlength]
    if rtype == 1 and rdlength == 4:  # A
        return {"type": "A", "value": ".".join(str(b) for b in rdata)}
    if rtype == 28 and rdlength == 16:  # AAAA
        parts = [f"{rdata[i]:02x}{rdata[i + 1]:02x}" for i in range(0, 16, 2)]
        ipv6 = ":".join(parts)
        try:
            ipv6 = str(ipaddress.IPv6Address(ipv6))
        except Exception:
            pass
        return {"type": "AAAA", "value": ipv6}
    if rtype == 5:  # CNAME
        cname = _decode_name(data, rdata_start)
        return {"type": "CNAME", "value": cname} if cname else None
    if rtype == 2:  # NS
        ns = _decode_name(data, rdata_start)
        return {"type": "NS", "value": ns} if ns else None
    if rtype == 15 and rdlength >= 3:  # MX
        preference = struct.unpack("!H", rdata[:2])[0]
        mx = _decode_name(data, rdata_start + 2)
        return {"type": "MX", "value": mx, "preference": preference} if mx else None
    if rtype == 16:  # TXT
        parts, pos = [], 0
        while pos < rdlength:
            slen = rdata[pos]; pos += 1
            if pos + slen <= rdlength:
                parts.append(rdata[pos:pos + slen].decode("utf-8", errors="replace"))
                pos += slen
        return {"type": "TXT", "value": " ".join(parts)} if parts else None
    if rtype == 6:  # SOA
        try:
            off = rdata_start
            mname = _decode_name(data, off); off = _skip_name(data, off)
            rname = _decode_name(data, off); off = _skip_name(data, off)
            if off + 20 <= rdata_start + rdlength and off + 20 <= len(data):
                serial = struct.unpack("!I", data[off:off + 4])[0]
                return {"type": "SOA", "value": mname, "mname": mname, "rname": rname, "serial": serial}
        except Exception:
            pass
    return None


def _parse_dns_response(data: bytes, tx_id: int) -> list[dict]:
    """Parse all sections (answer + authority + additional) of a DNS response."""
    if len(data) < 12:
        return []
    if struct.unpack("!H", data[:2])[0] != tx_id:
        return []

    qdcount = struct.unpack("!H", data[4:6])[0]
    ancount = struct.unpack("!H", data[6:8])[0]
    nscount = struct.unpack("!H", data[8:10])[0]
    arcount = struct.unpack("!H", data[10:12])[0]
    total = ancount + nscount + arcount

    if total == 0:
        return []

    offset = 12
    for _ in range(qdcount):
        offset = _skip_name(data, offset)
        offset += 4  # qtype + qclass
        if offset > len(data):
            return []

    seen: set[tuple] = set()
    records = []
    for _ in range(total):
        if offset >= len(data):
            break
        offset = _skip_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlength = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10
        rdata_start = offset
        if offset + rdlength > len(data):
            break
        offset += rdlength

        rec = _parse_rr(data, rtype, rdata_start, rdlength)
        if rec:
            key = (rec["type"], rec["value"])
            if key not in seen:
                seen.add(key)
                records.append(rec)

    return records


RCODE_NAMES = {
    0: "NOERROR",
    1: "FORMERR",
    2: "SERVFAIL",
    3: "NXDOMAIN",
    4: "NOTIMP",
    5: "REFUSED",
    6: "YXDOMAIN",
    7: "YXRRSET",
    8: "NXRRSET",
    9: "NOTAUTH",
    10: "NOTZONE",
}


class _DNSResult:
    """Result of a single DNS query attempt."""
    def __init__(self, records: list[dict], should_retry: bool, reason: str = ""):
        self.records = records
        self.should_retry = should_retry
        self.reason = reason

    @property
    def has_address(self) -> bool:
        """True if the response contains at least one A or AAAA record (domain is live)."""
        return any(r["type"] in ("A", "AAAA") for r in self.records)


async def _query_single(domain: str, resolver: str, qtype: int, timeout: float) -> _DNSResult:
    """Send a single DNS query and parse the full response (all sections)."""
    try:
        query, tx_id = _build_dns_query(domain, qtype)
        loop = asyncio.get_event_loop()
        transport, protocol = await asyncio.wait_for(
            loop.create_datagram_endpoint(
                lambda: _DNSProtocol(),
                remote_addr=(resolver, 53),
            ),
            timeout=timeout,
        )
        try:
            transport.sendto(query)
            data = await asyncio.wait_for(protocol.response_future, timeout=timeout)
        finally:
            transport.close()

        if len(data) >= 4:
            flags = struct.unpack("!H", data[2:4])[0]
            rcode = flags & 0x0F
            rcode_name = RCODE_NAMES.get(rcode, f"RCODE_{rcode}")
            if rcode in (2, 5):  # SERVFAIL / REFUSED — try another resolver
                return _DNSResult([], should_retry=True, reason=rcode_name)
            if rcode not in (0, 3):  # not NOERROR or NXDOMAIN — unrecoverable
                return _DNSResult([], should_retry=False, reason=rcode_name)
            records = _parse_dns_response(data, tx_id)
            return _DNSResult(records, should_retry=False, reason=rcode_name if rcode != 0 else "")

    except (asyncio.TimeoutError, TimeoutError):
        return _DNSResult([], should_retry=True, reason="TIMEOUT")
    except Exception:
        pass
    return _DNSResult([], should_retry=False, reason="DNS_ERROR")


async def _resolve_domain(domain: str, resolver: str, timeout: float) -> _DNSResult:
    """Query A then AAAA, parsing all response sections. Deduplicates across both responses."""
    all_records: list[dict] = []
    seen: set[tuple] = set()
    last_reason = ""

    for qtype in (1, 28):  # A then AAAA
        result = await _query_single(domain, resolver, qtype, timeout)
        if result.reason:
            last_reason = result.reason
        if result.should_retry:
            return _DNSResult(all_records, should_retry=True, reason=last_reason)
        for rec in result.records:
            key = (rec["type"], rec["value"])
            if key not in seen:
                seen.add(key)
                all_records.append(rec)
        # NXDOMAIN is definitive — no point querying AAAA
        if result.reason == "NXDOMAIN":
            break

    return _DNSResult(all_records, should_retry=False, reason=last_reason)


class _DNSProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.response_future = asyncio.get_event_loop().create_future()

    def datagram_received(self, data, addr):
        if not self.response_future.done():
            self.response_future.set_result(data)

    def error_received(self, exc):
        if not self.response_future.done():
            self.response_future.set_exception(exc)

    def connection_lost(self, exc):
        if not self.response_future.done():
            self.response_future.set_exception(exc or ConnectionError("closed"))


async def _check_asset(
    asset: dict,
    resolver_cycle,
    max_retries: int,
    semaphore: asyncio.Semaphore,
    ws_broadcast: Callable[[str], Awaitable[None]] | None,
    rate_limit_delay: float = 0,
) -> tuple[dict, bool]:
    """Resolve a single asset. Returns (asset, is_live). Mutates asset in place."""
    hostname = asset["hostname"]

    # IPs skip DNS — go straight to live
    if _is_ip(hostname) or asset.get("asset_type") == "ip":
        if ws_broadcast:
            await ws_broadcast(f"[+] {hostname} — IP address, skipping DNS")
        return asset, True

    async with semaphore:
        is_live = False
        used_resolver = None
        result = None
        for attempt in range(max_retries):
            resolver = next(resolver_cycle)
            result = await _resolve_domain(hostname, resolver, DNS_TIMEOUT)
            used_resolver = resolver

            if result.has_address:
                is_live = True
                break
            elif not result.should_retry:
                break
            # Timeout or rate-limited — try next resolver
            if ws_broadcast and attempt < max_retries - 1:
                await ws_broadcast(f"[*] {hostname} — {resolver} timed out, trying next resolver")
        if rate_limit_delay > 0:
            await asyncio.sleep(rate_limit_delay)

    if result and result.records:
        # Store the flat, deduplicated record set from this resolution, replacing
        # any prior records. Each record is a {type, value, ...} dict — the shape
        # the API and dashboard consume directly. (Previously these were wrapped
        # in a per-resolver envelope and prepended, which both hid the records
        # from the frontend and grew unbounded across repeated scans.)
        asset["dns_records"] = result.records

    if is_live:
        record_summary = ", ".join(f"{r['type']}={r['value']}" for r in result.records[:3])
        if ws_broadcast:
            await ws_broadcast(f"[+] {hostname} — {record_summary} (via {used_resolver})")
    else:
        asset["dns_fail_reason"] = result.reason if result and result.reason else "NO_RECORDS"
        if ws_broadcast:
            await ws_broadcast(f"[!] {hostname} — {asset['dns_fail_reason']}, skipping tech analysis")

    return asset, is_live


async def dns_precheck(
    assets: list[dict],
    ws_broadcast: Callable[[str], Awaitable[None]] | None = None,
    dns_rate_limit_delay: float | None = None,
    resolvers_path: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Run DNS pre-check on a list of asset dicts.

    Each asset dict must have: id, hostname, asset_type, dns_records.

    IPs skip DNS lookup and go straight to the live list.
    Domains are resolved in parallel (up to DNS_CONCURRENCY at once) against
    rotating resolvers.

    Returns:
        (live_assets, dead_assets)
        - live_assets: assets with A/AAAA records, dns_records populated
        - dead_assets: assets with no A/AAAA records, dns_records contains
          whatever the response carried (CNAME chain, NS, SOA, etc.)
    """
    rate_delay = dns_rate_limit_delay if dns_rate_limit_delay is not None else DNS_RATE_LIMIT_DELAY
    resolvers = _load_resolvers(resolvers_path)
    random.shuffle(resolvers)
    resolver_cycle = itertools.cycle(resolvers)
    max_retries = min(len(resolvers), 3)
    effective_concurrency = 1 if rate_delay > 0 else DNS_CONCURRENCY
    semaphore = asyncio.Semaphore(effective_concurrency)

    if ws_broadcast:
        await ws_broadcast(f"[*] DNS pre-check: validating {len(assets)} asset(s) against {len(resolvers)} resolver(s)")
        if rate_delay > 0:
            await ws_broadcast(f"[*] DNS rate limit: {rate_delay}s delay between probes (serial mode)")

    results = await asyncio.gather(*[
        _check_asset(asset, resolver_cycle, max_retries, semaphore, ws_broadcast, rate_limit_delay=rate_delay)
        for asset in assets
    ])

    live = [asset for asset, is_live in results if is_live]
    dead = [asset for asset, is_live in results if not is_live]

    if ws_broadcast:
        await ws_broadcast(f"[*] DNS pre-check complete: {len(live)} live, {len(dead)} dead")

    return live, dead
