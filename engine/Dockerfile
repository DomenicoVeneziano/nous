# ── Stage 1: compile ripgen (no pre-built binaries available) ─
FROM rust:slim AS ripgen-builder
RUN cargo install ripgen

# ── Stage 1b: build massdns from source ──────────────────────
FROM debian:bookworm-slim AS massdns-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git ca-certificates make \
    && git clone --depth=1 https://github.com/blechschmidt/massdns.git /tmp/massdns \
    && make -C /tmp/massdns \
    && rm -rf /var/lib/apt/lists/*

# ── Stage 2: runtime image ────────────────────────────────────
FROM debian:bookworm-slim

ARG TARGETARCH

# ── Apt packages (no Go, no Rust needed) ──────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    jq git curl ca-certificates xxd unzip \
    && rm -rf /var/lib/apt/lists/*

# ── Pre-built binaries ────────────────────────────────────────
RUN curl -sL "https://github.com/projectdiscovery/subfinder/releases/download/v2.13.0/subfinder_2.13.0_linux_${TARGETARCH}.zip" \
    -o /tmp/subfinder.zip && \
    unzip /tmp/subfinder.zip subfinder -d /usr/local/bin && \
    rm /tmp/subfinder.zip

RUN curl -sL "https://github.com/lc/gau/releases/download/v2.2.4/gau_2.2.4_linux_${TARGETARCH}.tar.gz" \
    -o /tmp/gau.tar.gz && \
    tar -xzf /tmp/gau.tar.gz -C /usr/local/bin gau && \
    rm /tmp/gau.tar.gz

RUN curl -sL "https://github.com/d3mondev/puredns/releases/download/v2.1.1/puredns-Linux-${TARGETARCH}.tgz" \
    -o /tmp/puredns.tgz && \
    tar -xzf /tmp/puredns.tgz -C /usr/local/bin puredns && \
    rm /tmp/puredns.tgz

# ── ripgen (compiled in stage 1) ─────────────────────────────
COPY --from=ripgen-builder /usr/local/cargo/bin/ripgen /usr/local/bin/ripgen

# ── massdns (compiled in stage 1b) ───────────────────────────
COPY --from=massdns-builder /tmp/massdns/bin/massdns /usr/local/bin/massdns

# ── crt wrapper ───────────────────────────────────────────────
RUN printf '#!/bin/bash\n\
DOMAIN="${@: -1}"\n\
curl -sf "https://crt.sh/?q=%%25.${DOMAIN}&output=json" \\\n\
  | jq "[.[] | .name_value | split(\"\\\\n\")[] | {subdomain: .}]"\n\
' > /usr/local/bin/crt && chmod +x /usr/local/bin/crt

# ── Python tools (waymore, camoufox, crawlee) ────────────────
# playwright is pinned: camoufox 0.4.x ships a Firefox build that speaks an
# older Juggler protocol. With an unpinned (newer) playwright the driver
# crashes on Firefox 'pageError' events that lack a 'location', aborting every
# navigation with status 0 (the SCAN_ERROR flood). 1.50.0 matches camoufox's Firefox.
RUN pip3 install --no-cache-dir --break-system-packages waymore camoufox "crawlee[playwright]" "playwright==1.50.0"

# ── Browsers for camoufox / crawlee ──────────────────────────
RUN python3 -m camoufox fetch
RUN python3 -m playwright install --with-deps firefox

# ── Engine dependencies ───────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY . .

CMD ["python3", "worker.py"]
