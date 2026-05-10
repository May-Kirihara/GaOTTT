#!/usr/bin/env bash
# Sweep Phase 2 of the GaOTTT LLM behavior study:
#   6 scenarios × 4 models × 3 runs = 72 cells.
#
# Features:
#   - Resumable: skips cells that already have meta.json
#   - Continue-on-failure: one bad cell doesn't abort the sweep
#   - Progress + summary
#
# Usage:
#   scripts/eval_run_phase2.sh                         # full sweep
#   scripts/eval_run_phase2.sh --dry-run               # list what would run
#   scripts/eval_run_phase2.sh --scenarios S00,S01     # subset of scenarios
#   scripts/eval_run_phase2.sh --models gemma-4-31b    # substring match on model list
#   scripts/eval_run_phase2.sh --runs 1                # runs per cell (default 3)
#
# Env:
#   RESULTS_ROOT   default /tmp/gaottt-eval-results
#   OPENCODE_PORT  default 14096 (passed through to eval_run_scenario.py)
set -uo pipefail  # NOTE: no -e — we continue on per-cell failures

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_ROOT="${RESULTS_ROOT:-/tmp/gaottt-eval-results}"
DATE="$(date +%Y-%m-%d)"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
RUNNER="${PROJECT_ROOT}/scripts/eval_run_scenario.py"

# --- 2x2 factorial model list -------------------------------------------------
ALL_MODELS=(
    "openrouter/google/gemma-4-31b-it"
    "openrouter/google/gemma-4-26b-a4b-it"
    "openrouter/qwen/qwen3.5-27b"
    "openrouter/qwen/qwen3.5-35b-a3b"
)

ALL_SCENARIOS=(S00 S01 S02 S05 S06 L01 L02)

# --- arg parsing --------------------------------------------------------------
DRY_RUN=0
RUNS_PER_CELL=3
SCEN_FILTER=""
MODEL_FILTER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=1; shift ;;
        --runs)       RUNS_PER_CELL="$2"; shift 2 ;;
        --scenarios)  SCEN_FILTER="$2"; shift 2 ;;
        --models)     MODEL_FILTER="$2"; shift 2 ;;
        -h|--help)    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            echo "unknown flag: $1" >&2; exit 1 ;;
    esac
done

# --- apply filters ------------------------------------------------------------
SCENARIOS=()
for s in "${ALL_SCENARIOS[@]}"; do
    if [[ -z "${SCEN_FILTER}" || ",${SCEN_FILTER}," == *",${s},"* ]]; then
        SCENARIOS+=("$s")
    fi
done
MODELS=()
for m in "${ALL_MODELS[@]}"; do
    if [[ -z "${MODEL_FILTER}" || "$m" == *"${MODEL_FILTER}"* ]]; then
        MODELS+=("$m")
    fi
done

TOTAL=$(( ${#SCENARIOS[@]} * ${#MODELS[@]} * RUNS_PER_CELL ))
echo "================================================================"
echo "  GaOTTT Phase 2 sweep"
echo "  scenarios : ${SCENARIOS[*]}"
echo "  models    : ${#MODELS[@]} models"
for m in "${MODELS[@]}"; do echo "              - $m"; done
echo "  runs/cell : ${RUNS_PER_CELL}"
echo "  total     : ${TOTAL} cells"
echo "  results   : ${RESULTS_ROOT}/${DATE}/"
echo "================================================================"

if [[ ${DRY_RUN} -eq 1 ]]; then
    for s in "${SCENARIOS[@]}"; do
        for m in "${MODELS[@]}"; do
            for r in $(seq 1 "${RUNS_PER_CELL}"); do
                echo "  would run: $s × $m × r=$r"
            done
        done
    done
    exit 0
fi

# --- sweep --------------------------------------------------------------------
i=0
passed=0
failed=0
skipped=0
started_at="$(date +%s)"

for s in "${SCENARIOS[@]}"; do
    scenario_path="${PROJECT_ROOT}/docs/research/scenarios/${s}.yaml"
    if [[ ! -f "${scenario_path}" ]]; then
        echo "⚠  no scenario file for $s at ${scenario_path} — skipping"
        continue
    fi

    for m in "${MODELS[@]}"; do
        m_safe="${m//\//_}"  # openrouter/google/gemma → openrouter_google_gemma
        m_safe="${m_safe//:/-}"

        for r in $(seq 1 "${RUNS_PER_CELL}"); do
            i=$((i + 1))
            meta="${RESULTS_ROOT}/${DATE}/${m_safe}/${s}/run-${r}/meta.json"

            if [[ -f "${meta}" ]]; then
                skipped=$((skipped + 1))
                echo "[$i/$TOTAL] SKIP  $s $m r=$r  (already done)"
                continue
            fi

            echo ""
            echo "[$i/$TOTAL] START $s $m r=$r"

            if "${PYTHON}" "${RUNNER}" -s "${scenario_path}" -m "$m" -r "$r" \
                    --results-root "${RESULTS_ROOT}"; then
                passed=$((passed + 1))
                echo "[$i/$TOTAL] OK    $s $m r=$r"
            else
                failed=$((failed + 1))
                echo "[$i/$TOTAL] FAIL  $s $m r=$r  (see ${meta%/*}/)"
            fi
        done
    done
done

elapsed=$(( $(date +%s) - started_at ))
echo ""
echo "================================================================"
echo "  DONE in ${elapsed}s  ·  passed=${passed}  failed=${failed}  skipped=${skipped}  total=${i}"
echo "  results: ${RESULTS_ROOT}/${DATE}/"
echo "================================================================"
