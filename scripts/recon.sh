#!/bin/bash

# ==============================================================================
# Nous — Unified Domain Reconnaissance & Bruteforce Pipeline
# ==============================================================================
# Merges active subdomain enumeration, DNS bruteforce with wildcard detection,
# permutation, and dynamic wordlist expansion into a single pipeline.
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Defaults
# ------------------------------------------------------------------------------
wordlist="/root/fuzzing/DNS/DNS.txt"
resolvers="/root/fuzzing/DNS/resolvers.txt"
wildcard_tests=10
wildcard_batch=20

# ------------------------------------------------------------------------------
# Usage
# ------------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $0 -d <domain> -o <output_file> [-s <known_subs>] [-w <wordlist>] [-r <resolvers>] [-n]

  -d  Target domain (required)
  -o  Output file for final results (required)
  -s  File of known subdomains to exclude from output (optional)
  -w  Wordlist for DNS bruteforce (default: $wordlist)
  -r  Resolvers file (default: $resolvers)
  -n  Skip DNS bruteforce and permutation steps
  -h  Show this help
EOF
    exit 1
}

# ------------------------------------------------------------------------------
# Dependency check
# ------------------------------------------------------------------------------
check_dependencies() {
    local deps=("subfinder" "crt" "jq" "gau" "waymore" "puredns" "ripgen" "awk" "sort" "grep" "mktemp" "xxd")
    for dep in "${deps[@]}"; do
        command -v "$dep" &>/dev/null || { echo "[!] Missing dependency: $dep"; exit 1; }
    done
}

# ------------------------------------------------------------------------------
# Parse arguments
# ------------------------------------------------------------------------------
while getopts "d:o:s:w:r:nh" opt; do
    case $opt in
        d) domain="$OPTARG" ;;
        o) output_file="$OPTARG" ;;
        s) subs_file="$OPTARG" ;;
        w) wordlist="$OPTARG" ;;
        r) resolvers="$OPTARG" ;;
        n) skip_bruteforce=1 ;;
        h) usage ;;
        ?) usage ;;
    esac
done

# ------------------------------------------------------------------------------
# Validate inputs
# ------------------------------------------------------------------------------
[[ -z "${domain:-}" || -z "${output_file:-}" ]] && {
    echo "[!] Error: -d <domain> and -o <output_file> are required."; usage;
}

if [[ -z "${skip_bruteforce:-}" ]]; then
    [[ ! -f "$wordlist" || ! -r "$wordlist" ]] && {
        echo "[!] Error: Wordlist '$wordlist' not found or unreadable."; exit 1;
    }
    # No wordlist ships with Nous — the operator supplies one. An empty file is
    # a hard error rather than a silent zero-result bruteforce.
    [[ ! -s "$wordlist" ]] && {
        echo "[!] Error: Wordlist '$wordlist' is empty."
        echo "[!]        DNS bruteforce needs a wordlist you provide. Populate it, e.g.:"
        echo "[!]          curl -sSL https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/DNS/subdomains-top1million-110000.txt \\"
        echo "[!]            -o '$wordlist'"
        echo "[!]        Or re-run the scan with DNS bruteforce disabled."
        exit 1
    }
    [[ ! -f "$resolvers" || ! -r "$resolvers" ]] && {
        echo "[!] Error: Resolvers '$resolvers' not found or unreadable."; exit 1;
    }
    [[ ! -s "$resolvers" ]] && {
        echo "[!] Error: Resolvers file '$resolvers' is empty. Add one resolver IP per line."; exit 1;
    }
fi

if [[ -n "${subs_file:-}" ]]; then
    [[ ! -f "$subs_file" || ! -r "$subs_file" ]] && {
        echo "[!] Error: Subdomains file '$subs_file' not found or unreadable."; exit 1;
    }
fi

output_dir=$(dirname "$output_file")
[[ ! -w "$output_dir" ]] && {
    echo "[!] Error: Output directory '$output_dir' is not writable."; exit 1;
}

check_dependencies

# ------------------------------------------------------------------------------
# Temp files & cleanup
# ------------------------------------------------------------------------------
active_subs=$(mktemp "${TMPDIR:-/tmp}/nous_active.XXXXXX")
bruteforced_subs=$(mktemp "${TMPDIR:-/tmp}/nous_brute.XXXXXX")
permuted_subs=$(mktemp "${TMPDIR:-/tmp}/nous_perm.XXXXXX")
combined_subs=$(mktemp "${TMPDIR:-/tmp}/nous_combined.XXXXXX")
wildcard_domains=$(mktemp "${TMPDIR:-/tmp}/nous_wildcard.XXXXXX")
new_words=$(mktemp "${TMPDIR:-/tmp}/nous_newwords.XXXXXX")
expanded_wordlist=$(mktemp "${TMPDIR:-/tmp}/nous_expanded_wl.XXXXXX")
filtered_wordlist=$(mktemp "${TMPDIR:-/tmp}/nous_filtered_wl.XXXXXX")
raw_archived_urls=$(mktemp "${TMPDIR:-/tmp}/nous_archived_urls.XXXXXX")
archived_urls_file="$(dirname "$output_file")/archived_urls.txt"
# source<TAB>hostname, one line per (source, host) pair. Written alongside the
# flat output file so the engine can attribute each subdomain to the phase that
# produced it instead of losing that in the Step 7 merge.
sources_file="$(dirname "$output_file")/subdomain_sources.tsv"

cleanup() {
    rm -f "$active_subs" "$bruteforced_subs" "$permuted_subs" \
          "$combined_subs" "$wildcard_domains" "$new_words" \
          "$expanded_wordlist" "$filtered_wordlist" "$raw_archived_urls" \
          "$output_file.tmp.$$" "$archived_urls_file.tmp.$$" "$sources_file.tmp.$$"
}
trap cleanup EXIT
# Convert a cancel/timeout signal into a normal exit so the EXIT trap above runs
# cleanup exactly once. Trapping the signals directly to cleanup would instead
# let the script resume after the handler and overwrite the checkpointed output
# file with the just-deleted working files, so we exit rather than clean inline.
trap 'exit 143' TERM
trap 'exit 130' INT

# ------------------------------------------------------------------------------
# Atomic file replacement
# ------------------------------------------------------------------------------
# Replace "$1" with whatever is read from stdin. Redirecting straight at the
# destination truncates it before the writer produces a byte, so a crash or a
# kill mid-write leaves a truncated or empty checkpoint that the engine then
# reads as authoritative. Staging in the same directory and renaming makes the
# swap atomic: readers see either the old file or the complete new one.
atomic_write() {
    local dest="$1"
    local tmp="${dest}.tmp.$$"
    cat > "$tmp" || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$dest"
}

# ------------------------------------------------------------------------------
# Incremental output flush
# ------------------------------------------------------------------------------
# Write every subdomain discovered so far to the final output file, applying the
# same known-subdomain filter as Step 8. Called as a checkpoint after each tool
# invocation so a cancelled or timed-out run leaves the maximum amount of partial
# results on disk: the output file is the engine's source of truth and is never
# removed by cleanup(), unlike the /tmp working files. Safe to call repeatedly;
# strips userinfo and ports inline so mid-step flushes (before the Step 1 dedup)
# stay clean. Every destination is replaced atomically.
flush_output() {
    # Strip any user:pass@ userinfo prefix before the port, otherwise
    # "user:pass@host" collapses to "user" instead of "host".
    cat "$active_subs" "$bruteforced_subs" "$permuted_subs" 2>/dev/null \
        | sed -e 's/^[^@]*@//' -e 's/:.*$//' \
        | sort -u > "$combined_subs" || true
    if [[ -n "${subs_file:-}" && -s "$subs_file" ]]; then
        grep -vFxf "$subs_file" "$combined_subs" 2>/dev/null \
            | atomic_write "$output_file" || true
    else
        atomic_write "$output_file" < "$combined_subs" 2>/dev/null || true
    fi
    # Persist archived URLs gathered so far too (gau/waymore stream into
    # raw_archived_urls); the engine's crawl-merge step reads archived_urls.txt.
    sort -u "$raw_archived_urls" 2>/dev/null \
        | atomic_write "$archived_urls_file" || true
    # Per-source attribution. Deliberately NOT filtered against subs_file: an
    # already-known host that bruteforce independently rediscovers has genuinely
    # been found by two sources, and the engine accumulates both tags.
    {
        awk -v s="Passive"      'NF {sub(/^[^@]*@/, ""); sub(/:.*$/, ""); print s"\t"$0}' "$active_subs"
        awk -v s="Bruteforce"   'NF {sub(/^[^@]*@/, ""); sub(/:.*$/, ""); print s"\t"$0}' "$bruteforced_subs"
        awk -v s="Permutations" 'NF {sub(/^[^@]*@/, ""); sub(/:.*$/, ""); print s"\t"$0}' "$permuted_subs"
    } 2>/dev/null | sort -u | atomic_write "$sources_file" || true
}

# ==============================================================================
#  STEP 1: Active Scanning (subfinder, crt.sh, gau, waymore)
# ==============================================================================
echo ""
echo "[+] ================================================================"
echo "[+]  Step 1: Active Subdomain Enumeration"
echo "[+] ================================================================"

# subfinder — passive enumeration via multiple sources
echo "[+] Running subfinder on $domain ..."
subfinder -d "$domain" -all -o "$active_subs" 2>/dev/null || true
flush_output  # checkpoint: subfinder results persisted

# crt.sh — certificate transparency logs
echo "[+] Querying crt.sh for $domain ..."
crt -s -json "$domain" 2>/dev/null \
    | jq -r '.[].subdomain' \
    | sed -e 's/^\*\.//' >> "$active_subs" || true
flush_output  # checkpoint: + crt.sh results

# gau — fetch known URLs from AlienVault, Wayback, etc., extract hostnames
echo "[+] Running gau on $domain ..."
echo "$domain" | gau --subs 2>/dev/null \
    | tee -a "$raw_archived_urls" \
    | awk -F/ '{print $3}' | sort -u >> "$active_subs" || true
flush_output  # checkpoint: + gau results & archived URLs

# waymore — fetch URLs, extract hostnames
echo "[+] Running waymore on $domain ..."
waymore -i "$domain" -mode U 2>/dev/null \
    | tee -a "$raw_archived_urls" \
    | awk -F/ '{print $3}' | sort -u >> "$active_subs" || true
flush_output  # checkpoint: + waymore results & archived URLs

# Strip userinfo prefixes (user:pass@host → host) and trailing port numbers
# (host:8080 → host), then deduplicate
sed -i'' -e 's/^[^@]*@//' -e 's/:.*$//' "$active_subs"
sort -u "$active_subs" -o "$active_subs"

# Write deduplicated archived URLs for the Python job to process
sort -u "$raw_archived_urls" | atomic_write "$archived_urls_file"

echo "[+] Active scan complete. Found $(wc -l < "$active_subs") unique subdomains."

# Persist active-scan results immediately so a cancel/timeout during the long
# bruteforce/permutation phases still saves what enumeration already found.
flush_output
echo ""

# ==============================================================================
#  STEP 2: Dynamic Wordlist Expansion
# ==============================================================================
# Parse discovered subdomains into individual word tokens and append novel
# entries to the bruteforce wordlist. This makes the subsequent bruteforce
# phase aware of naming patterns specific to the target.
#
# Logic:
#   sub.test.api.example.com  →  tokens: sub, test, api
#   (root domain "example" and TLD "com" are excluded)
# ==============================================================================
echo "[+] ================================================================"
echo "[+]  Step 2: Dynamic Wordlist Expansion"
echo "[+] ================================================================"

if [[ -n "${skip_bruteforce:-}" ]]; then
    echo "[*] DNS bruteforce disabled. Skipping wordlist expansion."
else
    # Determine how many labels the root domain has (e.g., example.com → 2, example.co.uk → 3).
    # We strip that many trailing labels from every subdomain before tokenising.
    root_label_count=$(echo "$domain" | awk -F. '{print NF}')

    # Work from a per-run copy so the original wordlist file is never modified.
    cp "$wordlist" "$expanded_wordlist"

    if [[ -s "$active_subs" ]]; then
        # For each subdomain, remove the trailing root_label_count labels, then
        # split the remaining labels into one word per line.
        awk -F. -v n="$root_label_count" '{
            # Number of subdomain-only labels
            count = NF - n
            for (i = 1; i <= count; i++) print $i
        }' "$active_subs" \
            | sort -u > "$new_words"

        # Append only words that are NOT already in the expanded wordlist
        if [[ -s "$new_words" ]]; then
            added=0
            while IFS= read -r word; do
                # Skip empty tokens
                [[ -z "$word" ]] && continue
                if ! grep -qxF "$word" "$expanded_wordlist"; then
                    echo "$word" >> "$expanded_wordlist"
                    ((added++)) || true
                fi
            done < "$new_words"
            echo "[+] Appended $added new word(s) to expanded wordlist."
        else
            echo "[*] No new tokens extracted from active scan results."
        fi
    else
        echo "[*] No active subdomains found. Skipping wordlist expansion."
    fi
fi
echo ""

# ==============================================================================
#  STEP 3: Wildcard Detection (pre-flight)
# ==============================================================================
# Probe the target with a random subdomain. If it resolves, wildcard DNS is
# present. puredns also filters wildcards internally, but this explicit check
# logs the finding for operator awareness.
# ==============================================================================
echo "[+] ================================================================"
echo "[+]  Step 3: Pre-flight Wildcard DNS Detection"
echo "[+] ================================================================"

wildcard_count=0
if [[ -n "${skip_bruteforce:-}" ]]; then
    echo "[*] DNS bruteforce disabled. Skipping wildcard detection."
else
    random_label="nous-wc-probe-$(head -c 8 /dev/urandom | xxd -p)"
    probe_result=$(echo "${random_label}.${domain}" \
        | puredns resolve -r "$resolvers" -q 2>/dev/null || true)

    if [[ -n "$probe_result" ]]; then
        echo "[!] WARNING: Wildcard DNS detected for $domain"
        echo "[!]          '${random_label}.${domain}' resolved successfully."
        echo "[!]          puredns wildcard filtering is active; verify results manually."
        echo "$domain" >> "$wildcard_domains"
        wildcard_count=1
    else
        echo "[*] No wildcard DNS detected for $domain"
    fi
fi
echo ""

# ==============================================================================
#  STEP 4: Wordlist Pre-filtering
# ==============================================================================
# Remove words whose direct first-level subdomain (word.target.com) is already
# present in known_subs, including www-prefixed variants (www.word.target.com).
# Multi-level subdomains (e.g. apple.car.target.com) do NOT cause any of their
# labels to be filtered — only exact first-level matches count.
# ==============================================================================
echo "[+] ================================================================"
echo "[+]  Step 4: Wordlist Pre-filtering"
echo "[+] ================================================================"

if [[ -n "${skip_bruteforce:-}" ]]; then
    echo "[*] DNS bruteforce disabled. Skipping wordlist pre-filtering."
else
    if [[ -n "${subs_file:-}" && -s "$subs_file" ]]; then
        # Single awk pass: build a lookup set of first-level labels from subs_file
        # (stripping www. prefix), then filter the expanded wordlist in O(n+m).
        removed=$(awk -v domain="$domain" -v out="$filtered_wordlist" '
            NR==FNR {
                line = $0
                sub(/^www\./, "", line)
                suffix = "." domain
                if (substr(line, length(line) - length(suffix) + 1) == suffix) {
                    prefix = substr(line, 1, length(line) - length(suffix))
                    if (prefix != "" && index(prefix, ".") == 0)
                        known[prefix] = 1
                }
                next
            }
            $0 != "" { if ($0 in known) { r++ } else { print > out } }
            END { print r+0 }
        ' "$subs_file" "$expanded_wordlist")
        echo "[+] Filtered out $removed known word(s). $(wc -l < "$filtered_wordlist") word(s) remaining."
    else
        cp "$expanded_wordlist" "$filtered_wordlist"
        echo "[*] No known-subdomains file provided. Using full wordlist."
    fi
fi
echo ""

# ==============================================================================
#  STEP 5: DNS Bruteforce
# ==============================================================================
# puredns bruteforce uses --wildcard-tests / --wildcard-batch to identify and
# filter wildcard IPs automatically.
# ==============================================================================
echo "[+] ================================================================"
echo "[+]  Step 5: DNS Bruteforce"
echo "[+] ================================================================"

if [[ -n "${skip_bruteforce:-}" ]]; then
    echo "[*] DNS bruteforce disabled. Skipping DNS bruteforce."
else
    echo "[+] Bruteforcing $domain with $(wc -l < "$filtered_wordlist") words ..."
    puredns bruteforce "$filtered_wordlist" "$domain" \
        -r "$resolvers" \
        --wildcard-tests "$wildcard_tests" \
        --wildcard-batch "$wildcard_batch" \
        -q >> "$bruteforced_subs" 2>/dev/null || true
    echo "[+] Bruteforce complete. Found $(wc -l < "$bruteforced_subs") resolved subdomains."
    flush_output
fi
echo ""

# ==============================================================================
#  STEP 6: Permutation & Resolution
# ==============================================================================
# Feed all bruteforced subdomains into ripgen for permutation, then resolve
# the candidates with wildcard filtering.
# ==============================================================================
echo "[+] ================================================================"
echo "[+]  Step 6: Permutation & Resolution"
echo "[+] ================================================================"

if [[ -s "$bruteforced_subs" ]]; then
    cat "$bruteforced_subs" \
        | ripgen \
        | puredns resolve \
            -r "$resolvers" \
            --wildcard-tests "$wildcard_tests" \
            --wildcard-batch "$wildcard_batch" \
            -q >> "$permuted_subs" 2>/dev/null || true
    echo "[+] Permutation complete. Found $(wc -l < "$permuted_subs") new subdomains."
    flush_output
else
    echo "[*] No bruteforced subdomains to permute. Skipping."
fi
echo ""

# ==============================================================================
#  STEP 7: Combine & Deduplicate
# ==============================================================================
echo "[+] ================================================================"
echo "[+]  Step 7: Combining & Deduplicating Results"
echo "[+] ================================================================"

cat "$active_subs" "$bruteforced_subs" "$permuted_subs" | sort -u > "$combined_subs"
echo "[+] Total unique subdomains: $(wc -l < "$combined_subs")"
echo ""

# ==============================================================================
#  STEP 8: Filter Known Subdomains
# ==============================================================================
echo "[+] ================================================================"
echo "[+]  Step 8: Filtering Known Subdomains"
echo "[+] ================================================================"

if [[ -n "${subs_file:-}" && -s "$subs_file" ]]; then
    echo "[+] Excluding entries found in $subs_file ..."
    grep -vFxf "$subs_file" "$combined_subs" | atomic_write "$output_file" || true
else
    echo "[*] No known-subdomains file provided. Writing all results."
    atomic_write "$output_file" < "$combined_subs"
fi
echo ""

# ==============================================================================
#  Summary
# ==============================================================================
echo "[+] ================================================================"
echo "[+]  Summary"
echo "[+] ================================================================"
echo "[+] Target domain    : $domain"
echo "[+] Output file      : $output_file"
echo "[+] Total new subs   : $(wc -l < "$output_file")"
if [[ "$wildcard_count" -gt 0 ]]; then
    echo "[!] Wildcard DNS     : DETECTED (review results manually)"
fi
echo "[+] ================================================================"
echo ""
