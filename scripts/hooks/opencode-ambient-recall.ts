/**
 * GaOTTT Ambient Recall — opencode plugin (the `UserPromptSubmit`-hook analogue).
 *
 * opencode's `chat.message` hook fires when a new user message is received.
 * This plugin reads the submitted message text, runs GaOTTT's `ambient_recall`
 * — a structured, passive (read-only, non-perturbing) recall — and appends the
 * resulting `<gaottt-ambient-recall>` block to the message, so long-term memory
 * surfaces automatically without the model having to call `recall` itself.
 *
 * It is the opencode counterpart of the Claude Code `UserPromptSubmit` hook
 * (`scripts/hooks/ambient_recall.py`) — same memory, same gravity field, just a
 * different agent frontend.
 *
 * Single source of truth: this plugin does NOT re-implement the MCP call. It
 * spawns the very same Python hook (`scripts/hooks/ambient_recall.py`), feeding
 * it `{"prompt": ...}` on stdin exactly as Claude Code does. Relevance gating,
 * slot composition, the `GAOTTT_AMBIENT_*` env tunables and the fail-safe
 * behaviour all live in one place — if the `ambient_recall` protocol changes,
 * both frontends move together.
 *
 * Passive throughout — never moves the gravity field. Fail-safe by
 * construction — any error, timeout or unreachable backend injects nothing and
 * never blocks the user's message.
 *
 * Install — copy (or symlink) this file into a plugin directory:
 *   global (every opencode session):   ~/.config/opencode/plugin/
 *   per-project:                       <project>/.opencode/plugin/
 * opencode auto-loads `*.ts` from there at startup. See
 * docs/wiki/Guides-Ambient-Recall.md.
 *
 * Tunables (environment variables) — the `GAOTTT_AMBIENT_*` set below the line
 * is read by the Python hook itself (URL / DIRECT_K / MIN_SCORE / TIMEOUT, see
 * scripts/hooks/ambient_recall.py). This shim adds / re-reads:
 *   GAOTTT_AMBIENT_RECALL     "0"/"false"/"off" disables the plugin (default on)
 *   GAOTTT_AMBIENT_MIN_CHARS  skip prompts shorter than this (default 12)
 *   GAOTTT_AMBIENT_TIMEOUT    Python hook hard timeout, seconds (default 6.0);
 *                             the subprocess is given a few extra seconds on
 *                             top so the Python side times out first.
 *   GAOTTT_REPO               GaOTTT repo root (default /mnt/holyland/Project/GaOTTT)
 *   GAOTTT_AMBIENT_PYTHON     interpreter (default $GAOTTT_REPO/.venv/bin/python)
 *   GAOTTT_AMBIENT_SCRIPT     hook script (default $GAOTTT_REPO/scripts/hooks/ambient_recall.py)
 *   GAOTTT_AMBIENT_DEBUG      if set to a file path, append step-by-step
 *                             diagnostics there (this plugin is otherwise
 *                             silent by design — same problem the Python hook
 *                             has — so this is the way to see what happened).
 */
import { appendFileSync } from "node:fs"
import type { Plugin } from "@opencode-ai/plugin"

const REPO = process.env.GAOTTT_REPO ?? "/mnt/holyland/Project/GaOTTT"
const PYTHON = process.env.GAOTTT_AMBIENT_PYTHON ?? `${REPO}/.venv/bin/python`
const SCRIPT =
  process.env.GAOTTT_AMBIENT_SCRIPT ?? `${REPO}/scripts/hooks/ambient_recall.py`

const _minChars = Number.parseInt(process.env.GAOTTT_AMBIENT_MIN_CHARS ?? "12", 10)
const MIN_CHARS = Number.isFinite(_minChars) ? _minChars : 12

// The Python hook enforces its own GAOTTT_AMBIENT_TIMEOUT and exits 0 with no
// output when it fires. Give the subprocess a little headroom on top so the
// Python side times out first (clean) rather than being killed mid-write.
const _timeoutSec = Number.parseFloat(process.env.GAOTTT_AMBIENT_TIMEOUT ?? "6.0")
const SPAWN_TIMEOUT_MS = (Number.isFinite(_timeoutSec) ? _timeoutSec : 6.0) * 1000 + 3000

const BLOCK_TAG = "<gaottt-ambient-recall>"
// A line the injected block always carries — distinctive enough that a user
// would never type it, so it detects a prior injection (opencode retries)
// without false-firing when the prompt merely *mentions* the tag string.
const INJECTED_MARKER = "GaOTTT 長期記憶から自動取得した関連知識"
const DEBUG = process.env.GAOTTT_AMBIENT_DEBUG

function dbg(msg: string): void {
  if (!DEBUG) return
  try {
    appendFileSync(DEBUG, `${new Date().toISOString()} ${msg}\n`)
  } catch {
    /* diagnostics must never throw */
  }
}

function disabled(): boolean {
  const v = (process.env.GAOTTT_AMBIENT_RECALL ?? "1").trim().toLowerCase()
  return v === "0" || v === "false" || v === "no" || v === "off" || v === ""
}

/** Run the Python ambient-recall hook; return its block, or null. */
async function ambientBlock(prompt: string): Promise<string | null> {
  const proc = Bun.spawn({
    cmd: [PYTHON, SCRIPT],
    stdin: new TextEncoder().encode(JSON.stringify({ prompt })),
    stdout: "pipe",
    stderr: "pipe",
    timeout: SPAWN_TIMEOUT_MS,
  })
  const [out, err] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ])
  const code = await proc.exited
  const block = out.trim()
  dbg(`spawn exit=${code} stdout=${block.length}c stderr=${err.trim().slice(0, 200)}`)
  return block.startsWith(BLOCK_TAG) ? block : null
}

export const GaotttAmbientRecall: Plugin = async () => {
  dbg(`plugin initialised (python=${PYTHON} script=${SCRIPT})`)
  return {
    "chat.message": async (input, output) => {
      try {
        if (disabled()) return

        // A submitted user message is a list of parts; the typed prompt is the
        // text parts (file attachments etc. are other part types).
        const textParts = output.parts.filter((p) => p.type === "text")
        dbg(
          `chat.message agent=${input.agent ?? "-"} parts=${output.parts.length} ` +
            `text-parts=${textParts.length} types=[${output.parts.map((p) => p.type).join(",")}]`,
        )
        if (textParts.length === 0) return

        const prompt = textParts
          .map((p) => p.text ?? "")
          .join("\n")
          .trim()
        if (prompt.length < MIN_CHARS) {
          dbg(`skip: prompt too short (${prompt.length}c)`)
          return
        }
        // Already enriched (e.g. opencode retried the message) — don't stack.
        if (prompt.includes(INJECTED_MARKER)) {
          dbg("skip: block already present")
          return
        }

        const block = await ambientBlock(prompt)
        if (!block) {
          dbg("no block (gate not passed / backend down) — silent")
          return
        }

        // Append the block to the last text part, mirroring how the Claude
        // Code hook appends context after the user's prompt.
        const last = textParts[textParts.length - 1]
        last.text = `${last.text}\n\n${block}`
        dbg(`injected ${block.length}c into part; new part length=${last.text.length}c`)
      } catch (e) {
        // Fail-safe: never block or perturb the user's message.
        dbg(`error: ${(e as Error)?.stack ?? String(e)}`)
      }
    },
  }
}
