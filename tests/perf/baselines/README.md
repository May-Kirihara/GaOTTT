# Perf baselines

JSON snapshots of Tier 6 metrics, one per perf-relevant change. Used by
``scripts/perf_diff.py`` to detect regressions across versions.

## Capturing a baseline

```bash
# Default — 200 docs, 100 recall calls, written to ./<UTC>_<sha>.json
.venv/bin/python scripts/perf_baseline.py

# Larger / smaller corpus
.venv/bin/python scripts/perf_baseline.py --corpus-size 500 --recall-calls 200

# Add a label for context (shows up in filename + diff output)
.venv/bin/python scripts/perf_baseline.py --label phase-l-stage-1
```

## Comparing baselines

```bash
# Latest vs second-latest
.venv/bin/python scripts/perf_diff.py

# Explicit pair
.venv/bin/python scripts/perf_diff.py before.json after.json

# Tighter threshold for CI gating
.venv/bin/python scripts/perf_diff.py --threshold 0.10
```

Exit code is 1 if any metric breached the regression threshold.

## What to commit

Commit baselines that mark *meaningful* points — major version changes,
phase boundaries, performance-relevant refactors. **Don't** commit
every run; the directory will grow without bound. A typical workflow:

1. Capture a `pre-change` baseline.
2. Make the change.
3. Capture a `post-change` baseline.
4. Run `perf_diff.py` and read the deltas.
5. Commit only `post-change` (or neither, if the change was neutral).

Pre-existing baselines stay around as historical reference points.
