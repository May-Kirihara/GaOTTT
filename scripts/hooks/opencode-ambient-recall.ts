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
 * it `{"prompt": ..., "history": [...], "recently_surfaced": {...}}` on stdin.
 * Claude Code passes a `transcript_path` instead and lets the Python side
 * scan it; opencode (no transcript file) extracts the same data from
 * `client.session.messages` and forwards it explicitly. Both paths converge
 * at the same downstream variables, so Stage 1 novelty + Refinement
 * Stage 4 multi-turn behave identically across frontends.
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
 *   GAOTTT_AMBIENT_HISTORY_TURNS  how many past user prompts to forward as the
 *                             `history` payload (default 2, 0 disables — same
 *                             as Claude Code's env). Read here too because the
 *                             plugin must know how many to pull from the SDK.
 *   GAOTTT_AMBIENT_NOVELTY_TURNS  how many past ambient blocks to scan for the
 *                             `<!-- ambient-ids ... -->` manifest, building
 *                             the `recently_surfaced` map (default 5, 0
 *                             disables).
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

const _historyTurns = Number.parseInt(
  process.env.GAOTTT_AMBIENT_HISTORY_TURNS ?? "2",
  10,
)
const HISTORY_TURNS = Number.isFinite(_historyTurns) && _historyTurns >= 0 ? _historyTurns : 0
const _noveltyTurns = Number.parseInt(
  process.env.GAOTTT_AMBIENT_NOVELTY_TURNS ?? "5",
  10,
)
const NOVELTY_TURNS = Number.isFinite(_noveltyTurns) && _noveltyTurns >= 0 ? _noveltyTurns : 0

const BLOCK_TAG = "<gaottt-ambient-recall>"
const CLOSE_TAG = "</gaottt-ambient-recall>"
// A line the injected block always carries — distinctive enough that a user
// would never type it, so it detects a prior injection (opencode retries)
// without false-firing when the prompt merely *mentions* the tag string.
const INJECTED_MARKER = "GaOTTT 長期記憶から自動取得した関連知識"
// `<!-- ambient-ids direct=id1,id2 lensing=id3 persona=id4 -->` — emitted by
// `services.formatters.format_ambient` at the bottom of every successful
// ambient block (Lateral Association Stage 1). Same regex the Python hook
// uses, ported to JS.
const MANIFEST_RE = /<!--\s*ambient-ids\s+(.+?)\s*-->/
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

/** Strip the appended ambient block (if any) from a previously-injected
 * message text. The plugin appends `\n\n<gaottt-ambient-recall>...</...>`
 * to the last text part; when we read past user prompts back we want the
 * *user's words*, not the injection we ourselves added. */
export function stripAmbientBlock(text: string): string {
  const i = text.indexOf(`\n\n${BLOCK_TAG}`)
  if (i < 0) return text
  return text.slice(0, i).trim()
}

/** Extract every node id from a `<!-- ambient-ids ... -->` line. Mirror of
 * the Python hook's `_ids_from_manifest`. Empty list when no manifest. */
export function idsFromManifest(text: string): string[] {
  const m = MANIFEST_RE.exec(text)
  if (!m) return []
  const out: string[] = []
  for (const chunk of m[1].split(/\s+/)) {
    const eq = chunk.indexOf("=")
    if (eq < 0) continue
    for (const nid of chunk.slice(eq + 1).split(",")) {
      const trimmed = nid.trim()
      if (trimmed) out.push(trimmed)
    }
  }
  return out
}

/** Build the (history, recently_surfaced) pair from past user messages of
 * this opencode session. The plugin appends ambient blocks to user message
 * text, so each past user text may carry a manifest from the previous
 * turn's injection — we read both signals from the same source. */
export function deriveHistoryAndRecency(
  texts: string[],
  historyTurns: number,
  noveltyTurns: number,
): { history: string[]; recently: Record<string, number> } {
  const history: string[] = []
  const recently: Record<string, number> = {}
  if (texts.length === 0) return { history, recently }

  if (historyTurns > 0) {
    for (const t of texts.slice(-historyTurns)) {
      const bare = stripAmbientBlock(t).trim()
      if (bare) history.push(bare)
    }
  }
  if (noveltyTurns > 0) {
    for (const t of texts.slice(-noveltyTurns)) {
      for (const id of idsFromManifest(t)) {
        recently[id] = (recently[id] ?? 0) + 1
      }
    }
  }
  return { history, recently }
}

/** Run the Python ambient-recall hook; return its block, or null. */
async function ambientBlock(
  prompt: string,
  history: string[],
  recently: Record<string, number>,
): Promise<string | null> {
  const payload: Record<string, unknown> = { prompt }
  if (history.length > 0) payload.history = history
  if (Object.keys(recently).length > 0) payload.recently_surfaced = recently
  const proc = Bun.spawn({
    cmd: [PYTHON, SCRIPT],
    stdin: new TextEncoder().encode(JSON.stringify(payload)),
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
  dbg(
    `spawn exit=${code} stdout=${block.length}c history=${history.length} ` +
      `recently=${Object.keys(recently).length} stderr=${err.trim().slice(0, 200)}`,
  )
  return block.startsWith(BLOCK_TAG) ? block : null
}

/** Pull the text of past user messages of this session from the OpenCode
 * SDK, oldest→newest. Returns at most ``max`` texts (the most recent ones).
 * Fail-safe to ``[]`` on SDK error / no client — the plugin still works,
 * it just loses the multi-turn + novelty channels for this turn. */
async function fetchPastUserTexts(
  client: { session: { messages: (opts: { path: { id: string } }) => Promise<{ data?: Array<{ info: { role?: string; time?: { created?: number } }; parts: Array<{ type?: string; text?: string }> }> }> } } | null,
  sessionID: string | undefined,
  max: number,
  currentMessageID: string | undefined,
): Promise<string[]> {
  if (!client || !sessionID || max <= 0) return []
  try {
    const resp = await client.session.messages({ path: { id: sessionID } })
    const rows = (resp.data ?? []).filter((r) => r.info.role === "user")
    // Drop the current message if it's in the list (it usually is — the hook
    // fires after the message is recorded). currentMessageID is best-effort;
    // if undefined we conservatively skip the newest row (= the in-flight
    // message) when we have at least one row.
    const filtered = rows.filter((r) => {
      const info = r.info as { id?: string }
      return currentMessageID ? info.id !== currentMessageID : true
    })
    const trimmed = currentMessageID ? filtered : filtered.slice(0, -1)
    const recent = trimmed.slice(-max)
    return recent.map((r) =>
      r.parts
        .filter((p) => p.type === "text")
        .map((p) => p.text ?? "")
        .join("\n"),
    )
  } catch (e) {
    dbg(`fetchPastUserTexts error: ${(e as Error)?.message ?? String(e)}`)
    return []
  }
}

export const GaotttAmbientRecall: Plugin = async (pluginInput) => {
  dbg(`plugin initialised (python=${PYTHON} script=${SCRIPT})`)
  // ``pluginInput.client`` is the OpenCode SDK; we type only the shape we
  // actually use so the plugin compiles without pulling in the full SDK type
  // chain (and works even if the SDK signature wiggles).
  const client = (pluginInput as { client?: unknown }).client as
    | Parameters<typeof fetchPastUserTexts>[0]
    | undefined
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

        // Lateral Association Stage 1 + Refinement Stage 4 parity — pull
        // past user texts from the session via the SDK so we can build the
        // same ``history`` (multi-turn concat) and ``recently_surfaced``
        // (per-id surface counts) maps the Claude Code hook scans from a
        // transcript file. Both signals flow through the same JSON payload
        // to the Python hook so the downstream code path is shared.
        const need = Math.max(HISTORY_TURNS, NOVELTY_TURNS)
        const pastTexts = await fetchPastUserTexts(
          client ?? null, input.sessionID, need, input.messageID,
        )
        const { history, recently } = deriveHistoryAndRecency(
          pastTexts, HISTORY_TURNS, NOVELTY_TURNS,
        )
        dbg(
          `extracted history=${history.length} recently=${Object.keys(recently).length} ` +
            `(from ${pastTexts.length} past user texts)`,
        )

        const block = await ambientBlock(prompt, history, recently)
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
