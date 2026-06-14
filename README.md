<h1 align="center">Nous</h1>

<p align="center">
  <strong>Self-hosted attack surface management for bug bounty hunters.</strong><br/>
  Orchestrate recon, fingerprint targets, crawl endpoints; surface results in a live, searchable dashboard.
</p>

---

## Summary

Nous is a self-hosted attack surface management platform built for bug bounty hunters. It wraps your recon toolchain in a persistent, observable execution layer; queuing scans, parsing output, indexing results, and streaming everything to a React dashboard via WebSocket. No more grepping flat files or losing context between sessions.

---

## Get Started

### Docker (recommended)

Requires Docker v24+ and Docker Compose v2+.

```bash
git clone https://github.com/DomenicoVeneziano/nous.git && cd nous
bash install/setup.sh && docker compose up --build -d
```

`setup.sh` generates a random `SECRET_KEY`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD`, writes them to `.env`, and prints them once. Dashboard: `http://localhost:3000` — API: `http://localhost:8000`.

---

## Features

### Recon Pipeline

Full subdomain enumeration via subfinder, amass, crt.sh, gau, and waymore; followed by DNS bruteforce with puredns + ripgen permutations, wildcard detection, and deduplication. Results are queued in a SQLite-backed job queue that survives restarts.

### Tech Detection & Crawling

Assets are fingerprinted using an embedded Wappalyzer engine driven by [Camoufox](https://camoufox.com); a stealth browser built to evade bot detection. It captures status codes, page titles, response headers, full DOM, and technology stacks. A network-intercepting crawler then extracts endpoints from the DOM, inline scripts, and XHR responses, and feeds newly discovered subdomains back into the pipeline.

### FTS5 Search

Structured multi-field queries with regex support across all indexed assets:

```
hostname:/^api\./ AND tech:nginx AND status:200
```

Supports export to JSON & CSV.

### REST API

A fully documented REST API is available — see [docs/api.md](docs/api.md) for details.

---

## License

MIT
