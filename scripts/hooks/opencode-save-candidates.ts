/**
 * GaOTTT Save Candidates — opencode plugin (the `Stop` + UserPromptSubmit-inject
 * pair analogue, collapsed into one hook).
 *
 * Claude Code splits "save candidates" across two hooks (Stop → state file →
 * next UserPromptSubmit) because its Stop hook stdout is NOT auto-injected.
 * opencode has no such restriction — the `chat.message` plugin hook can both
 * read the previous turn (via the SDK's session.messages) AND inject the
 * resulting block into the incoming user message in a single synchronous
 * pass. Same backend, same gravity field, same `<gaottt-save-candidates>`
 * block — just one hook instead of two.
 *
 * It is the opencode counterpart of the Claude Code Stop hook
 * (`scripts/hooks/save_candidates.py`) + UserPromptSubmit-inject hook
 * (`scripts/hooks/save_candidates_inject.py`). The block appears at the
 * *start of the next turn*, exactly like Claude Code's experience — the
 * lookback is on the just-completed (user N-1, assistant N-1) exchange.
 *
 * Single source of truth: this plugin does NOT re-implement the MCP call.
 * It spawns the very same Python hook (`scripts/hooks/save_candidates.py`)
 * with `GAOTTT_SAVE_CANDIDATES_EMIT=stdout`, feeding it a pre-built
 * `transcript` string on stdin (Claude Code passes a `transcript_path`
 * instead; both paths converge in `save_candidates.py:main`).
 *
 * Fail-safe by construction — any error, timeout, missing previous turn,
 * or unreachable backend injects nothing and never blocks the user's
 * message. First turn of a session is silent by design (no previous
 * exchange to evaluate).
 *
 * Install — copy (or symlink) this file into a plugin directory:
 *   global (every opencode session):   ~/.config/opencode/plugin/
 *   per-project:                       <project>/.opencode/plugin/
 * opencode auto-loads `*.ts` from there at startup. See
 * docs/wiki/Plans-Save-Candidates-Hook.md.
 *
 * Tunables (environment variables) — the `GAOTTT_SAVE_CANDIDATES_*` set is
 * read by the Python hook (URL / MAX / TIMEOUT / INCLUDE_PERSONA, see
 * scripts/hooks/save_candidates.py). This shim adds / re-reads:
 *   GAOTTT_SAVE_CANDIDATES_ENABLED  "0"/"false"/"off" disables (default on);
 *                                   shared switch with the Python side so a
 *                                   single env var kills the whole feature.
 *   GAOTTT_SAVE_CANDIDATES_TURNS    how many (user, assistant) pairs to feed
 *                                   the heuristic, fetched from session.messages
 *                                   (default 2). Mirrors the Claude Code env.
 *   GAOTTT_SAVE_CANDIDATES_TIMEOUT  Python hook hard timeout, seconds
 *                                   (default 3.0); the subprocess gets a few
 *                                   extra seconds on top so the Python side
 *                                   times out first.
 *   GAOTTT_REPO                     GaOTTT repo root
 *                                   (default /mnt/holyland/Project/GaOTTT)
 *   GAOTTT_SAVE_CANDIDATES_PYTHON   interpreter
 *                                   (default $GAOTTT_REPO/.venv/bin/python)
 *   GAOTTT_SAVE_CANDIDATES_SCRIPT   hook script
 *                                   (default $GAOTTT_REPO/scripts/hooks/save_candidates.py)
 *   GAOTTT_SAVE_CANDIDATES_DEBUG    if set to a file path, append step-by-step
 *                                   diagnostics there (this plugin is otherwise
 *                                   silent by design).
 */
import { appendFileSync } from "node:fs"
import type { Plugin } from "@opencode-ai/plugin"

const REPO = process.env.GAOTTT_REPO ?? "/mnt/holyland/Project/GaOTTT"
const PYTHON =
  process.env.GAOTTT_SAVE_CANDIDATES_PYTHON ?? `${REPO}/.venv/bin/python`
const SCRIPT =
  process.env.GAOTTT_SAVE_CANDIDATES_SCRIPT ??
  `${REPO}/scripts/hooks/save_candidates.py`

const _turns = Number.parseInt(
  process.env.GAOTTT_SAVE_CANDIDATES_TURNS ?? "2",
  10,
)
const HISTORY_TURNS = Number.isFinite(_turns) && _turns > 0 ? _turns : 2

// The Python hook enforces its own GAOTTT_SAVE_CANDIDATES_TIMEOUT and exits 0
// with no output on timeout / backend down. Give the subprocess a little
// headroom on top so the Python side times out first (clean) rather than
// being killed mid-write.
const _timeoutSec = Number.parseFloat(
  process.env.GAOTTT_SAVE_CANDIDATES_TIMEOUT ?? "3.0",
)
const SPAWN_TIMEOUT_MS =
  (Number.isFinite(_timeoutSec) ? _timeoutSec : 3.0) * 1000 + 3000

const BLOCK_TAG = "<gaottt-save-candidates>"
const CLOSE_TAG = "</gaottt-save-candidates>"
// A distinctive line the injected block always carries — used to detect a
// prior injection so an opencode retry on the same message does not stack
// blocks. Sourced from `services.formatters.format_save_candidates`.
const INJECTED_MARKER = "GaOTTT が直前ターンから抽出した save 候補"
const DEBUG = process.env.GAOTTT_SAVE_CANDIDATES_DEBUG

function dbg(msg: string): void {
  if (!DEBUG) return
  try {
    appendFileSync(DEBUG, `${new Date().toISOString()} ${msg}\n`)
  } catch {
    /* diagnostics must never throw */
  }
}

function disabled(): boolean {
  const v = (process.env.GAOTTT_SAVE_CANDIDATES_ENABLED ?? "1")
    .trim()
    .toLowerCase()
  return v === "0" || v === "false" || v === "no" || v === "off" || v === ""
}

/** Pull the last `pairs` user+assistant exchanges from this opencode session
 * via the SDK, oldest→newest. Skips the in-flight current user message (the
 * caller already has it). Fail-safe to `[]` on SDK error.
 *
 * Returned shape is `(role, text)` rows ready to render with the same
 * `[role] text` format `save_candidates.py:_build_transcript_from_path`
 * emits — both call sites converge on the same downstream heuristic. */
async function fetchRecentExchanges(
  client: {
    session: {
      messages: (opts: { path: { id: string } }) => Promise<{
        data?: Array<{
          info: {
            id?: string
            role?: string
            time?: { created?: number }
          }
          parts: Array<{ type?: string; text?: string }>
        }>
      }>
    }
  } | null,
  sessionID: string | undefined,
  pairs: number,
  currentMessageID: string | undefined,
): Promise<Array<[string, string]>> {
  if (!client || !sessionID || pairs <= 0) return []
  try {
    const resp = await client.session.messages({ path: { id: sessionID } })
    const rows = (resp.data ?? []).filter(
      (r) => r.info.role === "user" || r.info.role === "assistant",
    )
    // Drop the current in-flight user message (it's already in session.messages
    // by the time chat.message fires). Best-effort: prefer matching by id;
    // fall back to dropping the trailing user row.
    const trimmed = currentMessageID
      ? rows.filter((r) => (r.info as { id?: string }).id !== currentMessageID)
      : rows.length > 0 && rows[rows.length - 1].info.role === "user"
        ? rows.slice(0, -1)
        : rows
    // Each "pair" = 1 user + 1 assistant message. Take the last `pairs * 2`
    // rows as a generous slice (handles leading-assistant / trailing-user
    // transcripts uniformly).
    const slice = trimmed.slice(-Math.max(1, pairs * 2))
    return slice
      .map((r): [string, string] => {
        const role = r.info.role === "user" ? "user" : "assistant"
        const text = r.parts
          .filter((p) => p.type === "text")
          .map((p) => p.text ?? "")
          .join("\n")
          .trim()
        return [role, text]
      })
      .filter(([, t]) => t.length > 0)
  } catch (e) {
    dbg(`fetchRecentExchanges error: ${(e as Error)?.message ?? String(e)}`)
    return []
  }
}

/** Render the (role, text) rows in the same `[user] ... \n\n[assistant] ...`
 * shape `save_candidates.py:_build_transcript_from_path` produces. Keeping
 * the format identical means the downstream heuristic sees the same input
 * regardless of which frontend captured it. */
export function buildTranscriptString(rows: Array<[string, string]>): string {
  return rows.map(([r, t]) => `[${r}] ${t}`).join("\n\n")
}

/** Run the Python save-candidates hook in stdout-emit mode; return its block,
 * or null on any failure / no candidate. */
async function saveCandidatesBlock(transcript: string): Promise<string | null> {
  const payload = { transcript }
  const proc = Bun.spawn({
    cmd: [PYTHON, SCRIPT],
    stdin: new TextEncoder().encode(JSON.stringify(payload)),
    stdout: "pipe",
    stderr: "pipe",
    timeout: SPAWN_TIMEOUT_MS,
    env: { ...process.env, GAOTTT_SAVE_CANDIDATES_EMIT: "stdout" },
  })
  const [out, err] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ])
  const code = await proc.exited
  const block = out.trim()
  dbg(
    `spawn exit=${code} stdout=${block.length}c transcript=${transcript.length}c ` +
      `stderr=${err.trim().slice(0, 200)}`,
  )
  return block.startsWith(BLOCK_TAG) && block.endsWith(CLOSE_TAG) ? block : null
}

export const GaotttSaveCandidates: Plugin = async (pluginInput) => {
  dbg(`plugin initialised (python=${PYTHON} script=${SCRIPT})`)
  const client = (pluginInput as { client?: unknown }).client as
    | Parameters<typeof fetchRecentExchanges>[0]
    | undefined
  return {
    "chat.message": async (input, output) => {
      try {
        if (disabled()) return

        const textParts = output.parts.filter((p) => p.type === "text")
        if (textParts.length === 0) return

        // Already enriched (e.g. opencode retried the message) — don't stack.
        const promptText = textParts.map((p) => p.text ?? "").join("\n")
        if (promptText.includes(INJECTED_MARKER)) {
          dbg("skip: block already present")
          return
        }

        // Look back at the most recent completed exchange(s). On the very
        // first turn of a session there is no previous assistant message,
        // so `rows` is empty and we exit silently — by design.
        const rows = await fetchRecentExchanges(
          client ?? null,
          input.sessionID,
          HISTORY_TURNS,
          input.messageID,
        )
        if (rows.length === 0) {
          dbg("skip: no previous exchange (likely first turn)")
          return
        }

        const transcript = buildTranscriptString(rows)
        if (!transcript) {
          dbg("skip: empty transcript after rendering")
          return
        }

        const block = await saveCandidatesBlock(transcript)
        if (!block) {
          dbg("no block (no candidate / backend down) — silent")
          return
        }

        // Append after the user's text, mirroring how ambient_recall does it
        // — same shape, same position, so the model sees both blocks in a
        // predictable order at the bottom of the prompt.
        const last = textParts[textParts.length - 1]
        last.text = `${last.text}\n\n${block}`
        dbg(`injected ${block.length}c; new last-part length=${last.text.length}c`)
      } catch (e) {
        dbg(`error: ${(e as Error)?.stack ?? String(e)}`)
      }
    },
  }
}
