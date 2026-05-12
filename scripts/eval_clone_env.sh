#!/usr/bin/env bash
# Clone a GaOTTT data directory into an isolated sandbox for LLM behavior
# research. Uses sqlite3 .backup for WAL-safe DB copy + plain cp for FAISS.
#
# The production DB at ~/.local/share/gaottt/ is NEVER written to.
#
# Usage:
#   scripts/eval_clone_env.sh <tag>                     # empty sandbox
#   scripts/eval_clone_env.sh --snapshot <tag>          # snapshot prod
#   scripts/eval_clone_env.sh --from <src-dir> <tag>    # snapshot arbitrary dir
#   scripts/eval_clone_env.sh --list                    # list existing sandboxes
#   scripts/eval_clone_env.sh --rm <tag>                # remove a sandbox
#
# Output path: ${GAOTTT_EVAL_ROOT:-/tmp/gaottt-eval}/<tag>/
#
# After creation the script prints the env lines to source:
#   export GAOTTT_DATA_DIR=<path>
#   unset GAOTTT_CONFIG GER_RAG_CONFIG
set -euo pipefail

EVAL_ROOT="${GAOTTT_EVAL_ROOT:-/tmp/gaottt-eval}"
PROD_DIR="${GAOTTT_PROD_DIR:-${HOME}/.local/share/gaottt}"

usage() {
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-1}"
}

cmd_list() {
    if [[ ! -d "${EVAL_ROOT}" ]]; then
        echo "(no eval root at ${EVAL_ROOT})"
        return
    fi
    printf "%-32s %-12s %s\n" "TAG" "SIZE" "CREATED"
    for d in "${EVAL_ROOT}"/*/; do
        [[ -d "$d" ]] || continue
        tag="$(basename "$d")"
        size="$(du -sh "$d" 2>/dev/null | cut -f1)"
        created="$(stat -c '%y' "$d" 2>/dev/null | cut -d. -f1)"
        printf "%-32s %-12s %s\n" "${tag}" "${size}" "${created}"
    done
}

cmd_rm() {
    local tag="$1"
    local dest="${EVAL_ROOT}/${tag}"
    if [[ ! -d "${dest}" ]]; then
        echo "ERROR: no sandbox at ${dest}" >&2
        exit 1
    fi
    # Guard: never recurse into prod paths
    case "${dest}" in
        "${HOME}/.local/share/gaottt"*|"${HOME}/.local/share/ger-rag"*)
            echo "REFUSED: ${dest} looks like a prod path." >&2
            exit 2
            ;;
    esac
    rm -rf "${dest}"
    echo "Removed ${dest}"
}

snapshot_db() {
    local src="$1" dest="$2"
    if [[ ! -f "${src}/gaottt.db" ]]; then
        echo "ERROR: no gaottt.db at ${src}" >&2
        exit 1
    fi
    # Python stdlib sqlite3.backup() is WAL-aware; avoids depending on the
    # sqlite3 CLI which isn't always installed.
    python3 - "${src}/gaottt.db" "${dest}/gaottt.db" <<'PY'
import sqlite3, sys
src, dest = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dest) as d:
    s.backup(d)
PY
    for f in gaottt.faiss gaottt.faiss.ids; do
        if [[ -f "${src}/${f}" ]]; then
            cp "${src}/${f}" "${dest}/${f}"
        fi
    done
}

create_sandbox() {
    local tag="$1" mode="$2" src="${3:-}"
    local dest="${EVAL_ROOT}/${tag}"

    # Guard: tag must not be a path traversal
    case "${tag}" in
        */*|.*) echo "ERROR: tag must be a plain identifier, got '${tag}'" >&2; exit 1 ;;
    esac

    if [[ -e "${dest}" ]]; then
        echo "ERROR: ${dest} already exists. Pick another tag or --rm it first." >&2
        exit 1
    fi

    mkdir -p "${dest}"
    # If any step below fails (including `exit` inside snapshot_db),
    # remove the half-built sandbox so a re-run with the same tag
    # works without manual cleanup. ERR trap wouldn't catch `exit`;
    # EXIT always fires.
    _CLEANUP_DEST="${dest}"
    trap '[[ -n "${_CLEANUP_DEST:-}" ]] && rm -rf "${_CLEANUP_DEST}"' EXIT

    case "${mode}" in
        empty)
            ;;
        snapshot)
            snapshot_db "${PROD_DIR}" "${dest}"
            ;;
        from)
            snapshot_db "${src}" "${dest}"
            ;;
    esac

    # Bookkeeping: record provenance so `--list` and later audits can tell
    # whether the sandbox is empty, a prod snapshot, or copied from elsewhere.
    {
        echo "created_at=$(date -Iseconds)"
        echo "mode=${mode}"
        echo "source=${src:-${PROD_DIR}}"
        echo "tag=${tag}"
    } > "${dest}/.eval-meta"

    # Success: disarm the cleanup-on-exit trap so the sandbox survives.
    _CLEANUP_DEST=""

    echo "Created sandbox: ${dest} (mode=${mode})"
    echo ""
    echo "To use it:"
    echo "  export GAOTTT_DATA_DIR=${dest}"
    echo "  unset GAOTTT_CONFIG GER_RAG_CONFIG"
    echo ""
    echo "To tear it down:"
    echo "  $0 --rm ${tag}"
}

# --- arg parsing ---------------------------------------------------------

if [[ $# -eq 0 ]]; then usage; fi

MODE="empty"
SRC=""
TAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage 0 ;;
        --list)     cmd_list; exit 0 ;;
        --rm)       shift; [[ $# -eq 1 ]] || usage; cmd_rm "$1"; exit 0 ;;
        --snapshot) MODE="snapshot"; shift ;;
        --from)     MODE="from"; SRC="${2:?--from needs a path}"; shift 2 ;;
        -*)         echo "unknown flag: $1" >&2; usage ;;
        *)          TAG="$1"; shift ;;
    esac
done

if [[ -z "${TAG}" ]]; then
    echo "ERROR: tag is required" >&2
    usage
fi

create_sandbox "${TAG}" "${MODE}" "${SRC}"
