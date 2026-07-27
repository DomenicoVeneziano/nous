#!/bin/bash
# install/setup.sh — Nous setup: generates secure credentials and scaffolds data dirs.
#
# Usage (one-liner from project root):
#   bash install/setup.sh
#
# What it does:
#   1. Generates a cryptographically random SECRET_KEY (64 hex chars)
#   2. Generates a random ADMIN_USERNAME (nous_<8 hex chars>)
#   3. Generates a random ADMIN_PASSWORD (32 hex chars)
#   4. Writes them into .env, creating it from .env.example if absent
#   5. Creates the data directories, restoring the default resolver list if it
#      is missing or empty (the repo already ships one, so this is usually a
#      no-op) and creating an empty DNS wordlist you are expected to populate
#   6. Prints the generated credentials to the terminal
#
# It does NOT install dependencies: the Docker images build their own, and the
# bare-metal path printed at the end installs them explicitly.
#
# It is NOT idempotent: every run generates and injects fresh credentials,
# invalidating the previous ones. It warns before doing so on a re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

# ── Colors ────────────────────────────────────────────────────
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}  ███╗   ██╗ ██████╗ ██╗   ██╗███████╗${NC}"
echo -e "${CYAN}${BOLD}  ████╗  ██║██╔═══██╗██║   ██║██╔════╝${NC}"
echo -e "${CYAN}${BOLD}  ██╔██╗ ██║██║   ██║██║   ██║███████╗${NC}"
echo -e "${CYAN}${BOLD}  ██║╚██╗██║██║   ██║██║   ██║╚════██║${NC}"
echo -e "${CYAN}${BOLD}  ██║ ╚████║╚██████╔╝╚██████╔╝███████║${NC}"
echo -e "${CYAN}${BOLD}  ╚═╝  ╚═══╝ ╚═════╝  ╚═════╝ ╚══════╝${NC}"
echo ""
echo -e "  ${DIM}Attack Surface Management${NC}"
echo ""
echo -e "${BOLD}──────────────────────────────────────────────────────────${NC}"

# ── Step 1: Existing .env check ───────────────────────────────
# Re-running rotates credentials, so say so loudly instead of quietly breaking
# a working deployment.
if [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}[!]${NC} An .env already exists at ${ENV_FILE}"
    echo -e "${YELLOW}[!]${NC} It is kept as-is (not recreated from .env.example), but its"
    echo -e "${YELLOW}[!]${NC} SECRET_KEY, ADMIN_USERNAME and ADMIN_PASSWORD will be REPLACED."
    echo -e "${YELLOW}[!]${NC} The current admin login stops working and every issued JWT is"
    echo -e "${YELLOW}[!]${NC} invalidated. Back up your .env first if you need those values."
    echo -e "${YELLOW}[!]${NC} Press Ctrl-C within 5 seconds to abort..."
    sleep 5
    echo ""
fi

# ── Step 2: Generate credentials ──────────────────────────────
echo -e "${GREEN}[+]${NC} Generating cryptographic credentials..."

GEN_SECRET_KEY=$(openssl rand -hex 32)
GEN_ADMIN_USER="nous_$(openssl rand -hex 4)"
GEN_ADMIN_PASS=$(openssl rand -hex 16)

# ── Step 3: Write credentials to .env ─────────────────────────
if [ ! -f "$ENV_FILE" ]; then
    EXAMPLE_FILE="$PROJECT_DIR/.env.example"
    if [ ! -f "$EXAMPLE_FILE" ]; then
        echo -e "${RED}[!]${NC} Neither .env nor .env.example found at $PROJECT_DIR"
        echo -e "${RED}[!]${NC} Make sure you're running from the project root."
        exit 1
    fi
    echo -e "${GREEN}[+]${NC} Creating .env from .env.example..."
    cp "$EXAMPLE_FILE" "$ENV_FILE"
fi

echo -e "${GREEN}[+]${NC} Injecting credentials into .env..."

# sed only rewrites keys that are already present. A hand-written .env missing
# one would silently keep no value at all and the app would fall back to the
# placeholder baked into backend/config.py, so append whatever is absent.
set_env_var() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        # Use platform-safe sed (macOS vs Linux)
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
        else
            sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
        fi
    else
        echo -e "${YELLOW}[!]${NC} ${key} was missing from .env — appending it."
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

set_env_var SECRET_KEY "$GEN_SECRET_KEY"
set_env_var ADMIN_USERNAME "$GEN_ADMIN_USER"
set_env_var ADMIN_PASSWORD "$GEN_ADMIN_PASS"

# ── Step 4: Create data directories ──────────────────────────
echo -e "${GREEN}[+]${NC} Creating data directories..."
mkdir -p "$PROJECT_DIR/data/db"
mkdir -p "$PROJECT_DIR/data/projects"
mkdir -p "$PROJECT_DIR/data/wordlists"
mkdir -p "$PROJECT_DIR/data/resolvers"

# The repo ships a default resolver list, so this normally does nothing; it only
# restores the file if it went missing or was emptied. Existing files are left
# untouched so user customisations are preserved.
RESOLVERS_FILE="$PROJECT_DIR/data/resolvers/resolvers.txt"
if [ ! -s "$RESOLVERS_FILE" ]; then
    echo -e "${GREEN}[+]${NC} Seeding default DNS resolvers..."
    cat > "$RESOLVERS_FILE" <<'EOF'
8.8.8.8
8.8.4.4
1.1.1.1
1.0.0.1
9.9.9.9
149.112.112.112
208.67.222.222
208.67.220.220
EOF
fi
# No DNS wordlist is bundled — you supply your own. The empty placeholder keeps
# the configured path valid; recon refuses to bruteforce until it has content.
WORDLIST_FILE="$PROJECT_DIR/data/wordlists/dns_wordlist.txt"
[ -f "$WORDLIST_FILE" ] || touch "$WORDLIST_FILE"
if [ ! -s "$WORDLIST_FILE" ]; then
    echo -e "${YELLOW}[!]${NC} No DNS wordlist bundled. data/wordlists/dns_wordlist.txt is empty."
    echo -e "${YELLOW}[!]${NC} DNS bruteforce is off by default; populate the file before enabling it, e.g."
    echo -e "    ${DIM}curl -sSL https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/DNS/subdomains-top1million-110000.txt \\${NC}"
    echo -e "    ${DIM}  -o data/wordlists/dns_wordlist.txt${NC}"
fi

# ── Step 5: Print credentials ────────────────────────────────
echo ""
echo -e "${BOLD}──────────────────────────────────────────────────────────${NC}"
echo -e "${GREEN}${BOLD}  Setup complete.${NC}"
echo -e "${BOLD}──────────────────────────────────────────────────────────${NC}"
echo ""
echo -e "  ${BOLD}Your generated credentials:${NC}"
echo ""
echo -e "    ${DIM}SECRET_KEY${NC}      ${YELLOW}${GEN_SECRET_KEY}${NC}"
echo -e "    ${DIM}ADMIN_USERNAME${NC}  ${YELLOW}${GEN_ADMIN_USER}${NC}"
echo -e "    ${DIM}ADMIN_PASSWORD${NC}  ${YELLOW}${GEN_ADMIN_PASS}${NC}"
echo ""
echo -e "  ${RED}${BOLD}Save these now. They will not be shown again.${NC}"
echo -e "  ${DIM}They are also stored in:${NC} ${ENV_FILE}"
echo ""
echo -e "${BOLD}──────────────────────────────────────────────────────────${NC}"
echo ""
echo -e "  ${BOLD}Start Nous:${NC}"
echo ""
echo -e "    ${DIM}# Docker (recommended)${NC}"
echo -e "    docker compose up --build -d"
echo ""
echo -e "    ${DIM}# Or bare-metal — install dependencies first, then 3 terminals${NC}"
echo -e "    ${DIM}# The recon pipeline shells out to an external toolchain that is NOT${NC}"
echo -e "    ${DIM}# installed here: subfinder, gau, waymore, crt, puredns, massdns, ripgen, jq.${NC}"
echo -e "    bash install/check_deps.sh   ${DIM}# verify the toolchain + runtime, prints install hints${NC}"
echo -e "    pip install -r backend/requirements.txt -r engine/requirements.txt"
echo -e "    (cd frontend && npm install)"
echo -e "    cd backend  && uvicorn main:app --reload --port 8000"
echo -e "    cd engine   && python worker.py"
echo -e "    cd frontend && npm run dev"
echo ""
echo -e "  ${DIM}Dashboard:${NC}  http://localhost:3000"
echo -e "  ${DIM}API:${NC}        http://localhost:8000"
echo ""
echo -e "${BOLD}──────────────────────────────────────────────────────────${NC}"
echo ""
