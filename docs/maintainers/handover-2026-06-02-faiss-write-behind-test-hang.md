# Handover — FAISS write-behind flake + hang (2026-06-02, resolved 2026-06-03)

**Author**: Claude (Opus 4.8). Surfaced while merging Lateral Association Stage 8
/ Synaptic Pruning (#39, #40). **v1 of this doc proposed the wrong primary
hypothesis for the flake** (to_thread saturation / save delayed past the poll).
Verified testing (deterministic repro + full-suite reruns + an independent
GLM-5.1 review) corrected it to a **torn `.faiss`/`.ids` read**. This v2 records
the true causes, the fixes applied, and the residuals.

## Status

| Issue | State |
|---|---|
| **FLAKE** (intermittent `0 == 4` / "not saved") | ✅ **fixed + verified** — torn-read root cause, test-poll fix |
| **HANG** (~2h isolation block) | 🟡 **mitigated** — root vulnerability bounded; genuine-deadlock tail deferred; never reproduced on demand |

## FLAKE — root cause (corrected) and fix

**Root cause = torn `.faiss`/`.ids` read.** `FaissIndex.save()`
(`gaottt/index/faiss_index.py`) commits the index and its id-map sidecar with
**two separate `os.replace` calls** — `.faiss` first (~`:95`), then `.ids`
(~`:104`). A reader that gates only on the `.faiss` file can observe a
half-published pair (`.faiss` new, `.ids` absent/stale). `FaissIndex.load()`
then hits its id-map/ntotal **mismatch guard (~`:133`)** and `reset()`s the
index to **empty**. The test's visibility assertion then fails as `0 == 4`.
Intermittent because it is a timing window (whether `engine_b.load()` lands
inside it). The "save delayed under load" framing in v1 was a symptom, not the
cause.

**Deterministic proof** (run this session): with a saved index, deleting/
shrinking the `.ids` sidecar makes `FaissIndex.load()` return **size 0** even
though `.faiss` is non-empty — exactly the flake. And the old poll gate
(`os.path.exists(path) and getsize > 0`, `.faiss` only) returns **True** in that
torn state, so the test exited its wait prematurely.

**Fix (test-side, applied):** the save-completion poll in both
`tests/integration/test_engine_faiss_write_behind.py` and
`...virtual_faiss_write_behind.py` now gates on **both** `.faiss` non-empty
**and** the `.ids` sidecar's non-empty line-count == `len(ids)` (new
`_ids_line_count` helper), not `.faiss` alone. Sound because: fresh `tmp_path`
(no stale `.ids`), `os.replace` is atomic (never a partial line), and
`.faiss`-before-`.ids` ordering means a matching `.ids` implies `.faiss` is
already committed.

**Verification (the real test):**
- Deterministic repro of the torn-read mechanism + the fix's gate logic.
- **Full suite ×3 post-fix: 760 passed, write-behind clean every run** (pre-fix
  flaked under the same conditions).
- **Independent GLM-5.1 review** reached the same conclusion: the `.ids`-count
  gate fully closes the window for this test (noting only a non-applicable
  multi-save stale-match edge case).

### Production note (not the test) — left as-is, intentionally

The torn read also exists for a real second process (`engine_b.startup()` in
production). `load()`'s mismatch guard self-heals it (reset → the startup
diagnostic rebuilds from the store). That rebuild is **correct but expensive**
(O(N) RURI re-embed) — acceptable because torn reads are rare and transient.
A reviewer (GLM) suggested swapping the save order (`.ids` before `.faiss`);
that is **incomplete** — it only removes the cold-start window, leaves a
mirror-image window for incremental re-saves, and would break the test fix
(which relies on `.faiss`-first). The only *fully* atomic production fix is
single-file persistence (embed the id-map inside the FAISS file → one
`os.replace`). Deferred: not worth the change given rarity + self-heal.

## HANG — vulnerability, fix, residual

**Root vulnerability (consensus of my analysis + GLM):**
`engine.shutdown()`'s **final save was an unbounded `await asyncio.to_thread(
self.faiss_index.save, ...)` with no `wait_for` timeout** — unlike the periodic-
task awaits above it (`wait_for(timeout=10.0)`). Any wedged save blocked
shutdown forever.

Two triggers, one shared defect:
- **GLM's mechanism (main / post-#38 only):** `_faiss_save_task.cancel()` does
  **not** interrupt an in-flight `to_thread` worker; that worker keeps running
  holding `FaissIndex._lock`, and the final save's `to_thread(save)` then blocks
  acquiring the same lock → deadlock if `write_index` is slow.
- **My note:** the originally-observed ~2h hang was on the
  `feat/synaptic-pruning-edge-decay` branch, which **predates #38 and has no
  lock** (`git merge-base --is-ancestor 1450c2d 5c59ace` → false). So that hang
  was not the lock; likely executor/teardown — but it shares the same unbounded-
  await defect.

**Fix applied (this PR):**
1. `engine.shutdown()` wraps both final saves in
   `asyncio.wait_for(..., timeout=config.faiss_final_save_timeout_seconds)`
   (default **30s**). On timeout it logs and proceeds — durability preserved by
   the startup rebuild. Shutdown can no longer hang indefinitely.
2. **`pytest-timeout` added** (`pyproject.toml` dev dep + `[tool.pytest.ini_
   options] timeout = 120, timeout_method = "signal"`). Any future hang now
   fails fast **with a thread-stack dump** of where it blocked — the capture
   tool v1 lacked, and a guard so a hang can never wedge CI/local runs for hours.

**Residual / not fully closed:**
- `wait_for` cancels the *await* but cannot interrupt the worker *thread*. For a
  genuine `write_index` deadlock (thread stuck holding `_lock`), shutdown now
  returns, but the non-daemon worker could still delay interpreter exit. The
  deeper fix is **not holding `FaissIndex._lock` across the entire write**
  (e.g. snapshot under lock, write outside it) or a dedicated single-thread
  executor for FAISS I/O. Deferred — needs the hang reproduced first.
- **Never reproduced on demand:** 25 isolated iterations under
  `faulthandler` + `timeout -s ABRT 75` caught no hang. It is rare. If it recurs,
  pytest-timeout (signal) will now print the stack — attach that to this doc.

## Code pointers

- `gaottt/index/faiss_index.py`: `save()` (two `os.replace`, ~`:95`/`:104`),
  `load()` (mismatch guard `reset()` ~`:133`), `_lock` (#38).
- `gaottt/core/engine.py`: `shutdown()` final save now `wait_for`-bounded
  (~`:265`); `_faiss_save_loop` (~`:328`).
- `gaottt/config.py`: `faiss_final_save_timeout_seconds` (default 30).
- `pyproject.toml`: `pytest-timeout`, `timeout = 120`.
- Tests: `tests/integration/test_engine_faiss_write_behind.py`,
  `tests/integration/test_engine_virtual_faiss_write_behind.py`
  (`_ids_line_count` poll gate).
- Related: [Operations — Troubleshooting](../wiki/Operations-Troubleshooting.md)
  問題5.5 (reverse-overwrite guard); multi-process write-behind notes in `CLAUDE.md`.
