#!/bin/bash
# install/check_deps.sh — Validates all tool dependencies for bare-metal install

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'

echo ""
echo "[*] Nous Dependency Check"
echo "============================"
echo ""

MISSING=()

# ── Recon toolchain (used by scripts/recon.sh) ────────────────
echo -e "${DIM}Recon toolchain:${NC}"

RECON_DEPS=(subfinder gau puredns ripgen massdns crt jq waymore)
for dep in "${RECON_DEPS[@]}"; do
    if command -v "$dep" &>/dev/null; then
        echo -e "  ${GREEN}[OK]${NC} $dep"
    else
        echo -e "  ${RED}[MISSING]${NC} $dep"
        MISSING+=("$dep")
    fi
done

# ── Runtime (backend, engine, frontend) ──────────────────────
echo ""
echo -e "${DIM}Runtime:${NC}"

RUNTIME_DEPS=(python3 pip node npm)
for dep in "${RUNTIME_DEPS[@]}"; do
    if command -v "$dep" &>/dev/null; then
        echo -e "  ${GREEN}[OK]${NC} $dep"
    else
        echo -e "  ${RED}[MISSING]${NC} $dep"
        MISSING+=("$dep")
    fi
done

echo ""

if [ ${#MISSING[@]} -eq 0 ]; then
    echo -e "${GREEN}All dependencies satisfied.${NC}"
    exit 0
else
    echo -e "${RED}Missing ${#MISSING[@]} dependencies: ${MISSING[*]}${NC}"
    echo ""
    echo -e "${YELLOW}Install hints:${NC}"
    echo "  Go tools:    go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"
    echo "               go install github.com/lc/gau/v2/cmd/gau@latest"
    echo "               go install github.com/d3mondev/puredns/v2@latest"
    echo "  Rust tools:  cargo install ripgen"
    echo "  Pip tools:   pip install crt waymore"
    echo "  Apt tools:   apt install massdns jq"
    echo ""
    exit 1
fi
