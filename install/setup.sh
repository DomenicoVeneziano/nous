#!/bin/bash
# install/setup.sh — Nous setup: generates secure credentials, scaffolds data dirs, installs deps.
#
# Usage (one-liner from project root):
#   bash install/setup.sh
#
# What it does:
#   1. Generates a cryptographically random SECRET_KEY (64 hex chars)
#   2. Generates a random ADMIN_USERNAME (nous_<8 hex chars>)
#   3. Generates a random ADMIN_PASSWORD (32 hex chars)
#   4. Writes them into .env (replacing placeholders)
#   5. Creates data directories
#   6. Installs backend, engine, and frontend dependencies
#   7. Prints the generated credentials to the terminal

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

# ── Step 1: Generate credentials ──────────────────────────────
echo -e "${GREEN}[+]${NC} Generating cryptographic credentials..."

GEN_SECRET_KEY=$(openssl rand -hex 32)
GEN_ADMIN_USER="nous_$(openssl rand -hex 4)"
GEN_ADMIN_PASS=$(openssl rand -hex 16)

# ── Step 2: Write credentials to .env ─────────────────────────
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

# Use platform-safe sed (macOS vs Linux)
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|^SECRET_KEY=.*|SECRET_KEY=${GEN_SECRET_KEY}|" "$ENV_FILE"
    sed -i '' "s|^ADMIN_USERNAME=.*|ADMIN_USERNAME=${GEN_ADMIN_USER}|" "$ENV_FILE"
    sed -i '' "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${GEN_ADMIN_PASS}|" "$ENV_FILE"
else
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${GEN_SECRET_KEY}|" "$ENV_FILE"
    sed -i "s|^ADMIN_USERNAME=.*|ADMIN_USERNAME=${GEN_ADMIN_USER}|" "$ENV_FILE"
    sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${GEN_ADMIN_PASS}|" "$ENV_FILE"
fi

# ── Step 3: Create data directories ──────────────────────────
echo -e "${GREEN}[+]${NC} Creating data directories..."
mkdir -p "$PROJECT_DIR/data/db"
mkdir -p "$PROJECT_DIR/data/projects"
mkdir -p "$PROJECT_DIR/data/wordlists"
mkdir -p "$PROJECT_DIR/data/resolvers"

# Seed DNS resolvers + wordlist if absent (required by DNS bruteforce recon).
# Existing files are left untouched so user customisations are preserved.
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
WORDLIST_FILE="$PROJECT_DIR/data/wordlists/dns_wordlist.txt"
[ -f "$WORDLIST_FILE" ] || touch "$WORDLIST_FILE"

# ── Step 4: Print credentials ────────────────────────────────
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
echo -e "    ${DIM}# Or bare-metal (3 terminals)${NC}"
echo -e "    cd backend  && uvicorn main:app --reload --port 8000"
echo -e "    cd engine   && python worker.py"
echo -e "    cd frontend && npm run dev"
echo ""
echo -e "  ${DIM}Dashboard:${NC}  http://localhost:3000"
echo -e "  ${DIM}API:${NC}        http://localhost:8000"
echo ""
echo -e "${BOLD}──────────────────────────────────────────────────────────${NC}"
echo ""
