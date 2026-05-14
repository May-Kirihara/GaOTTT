---
name: gaottt
description: Long-term memory across sessions. Recall is biased by a gravity field, so frequently co-recalled memories drift together over time. Use to restore prior context at session start, save important decisions / lessons, evacuate context before compaction, and surface past failures when hitting similar problems.
---

# GaOTTT: long-term memory

External long-term memory across sessions. Backed by embeddings + a gravity-simulation that biases recall toward co-occurring and recently-touched memories. The full design rationale (physics ↔ TTT ↔ astrocyte correspondence, Phase A–L history) lives in [`docs/wiki/`](docs/wiki/Home.md) — this file is the operational reference.

## When to use

### `recall` — retrieve past memories
- **Session start.** Load the prior session's summary with `source_filter=["compaction","agent"]`.
- **User uses temporal pointers** ("last time", "before", "we already…").
- **You hit an error.** Past troubleshooting will surface.
- **Before an important design judgment** — align with prior decisions.

### `remember` — save knowledge
- **User states a preference / constraint / prohibition** → `source="user"`.
- **A problem actually gets solved** → save the cause AND fix together, `source="agent"`.
- **A judgment fails or is retracted** → `tags=["mistake","retracted"]`.
- **Iterative thinking flips your conclusion** → save the new one and `relate(edge_type="supersedes")` the old.
- **Sense compaction approaching** → evacuate session summary with `source="compaction"`.
- **Note explicitly for future you** → `tags=["letter-to-future-self"]`.

### `explore` — serendipitous discovery
- Looping in the same potential well.
- Cross-domain transfer wanted.
- User asks "got any interesting ideas?".

### `reflect` — inspect memory state
- **Session end**: `aspect="hot_topics"` to see the day's mass accretion.
- **Periodic pruning**: `aspect="dormant"` → confirm with user → `forget`.
- **Duplicate cleanup**: `aspect="duplicates"` → `merge`.

### `prefetch` — pre-warm recall
- Start of a turn when you can predict what the user will probe.
- Right after parsing user input, while you compose your response.

### Phase D — persona + tasks
- **Session start**: `inherit_persona()` to wear past values / intentions / commitments.
- Deeply-held belief → `declare_value`. Long-term direction → `declare_intention`. Time-bounded promise → `declare_commitment`.
- Action items → `commit` → `start` → `complete` / `abandon`.

---

## Tools

### remember

```
remember(content, source="agent", tags=None, context=None,
        ttl_seconds=None, emotion=0.0, certainty=1.0)
```

- `source`: `agent` (your own), `user`, `compaction`, `system`, `hypothesis` (auto-expires 7 days).
- `emotion ∈ [-1.0, 1.0]`: magnitude (not sign) boosts recall — both elation and frustration deserve to surface.
- `certainty ∈ [0.0, 1.0]`: 30-day half-life decay unless `revalidate`-d.

```
remember(content="No pip; use uv", source="user", tags=["preference"])
remember(content="Phase L Stage 1 完了 (BM25 union seed)", source="compaction")
remember(content="Idea: learnable temperature for explore", source="hypothesis")
remember(content="Finally fixed the FAISS leak", emotion=0.8, certainty=0.9)
```

### recall

```
recall(query, top_k=5, source_filter=None, wave_depth=None, wave_k=None,
       force_refresh=False, persona_context=None, tag_filter=None,
       output_mode="full")
```

- `output_mode` — `"compact"` (content truncated at 300 chars; **prefer this for triage**), `"ids"` (header only — id, scores, tags), `"full"` (complete content, default).
- `source_filter` — restrict to one or more source classes (e.g. `["agent","compaction"]`). Effective at the seed step. For sparse classes on a large DB, pass `wave_k=1000` to widen the seed pool.
- `persona_context` — list of declared value / intention / commitment ids. Force-injects them into both the seed pool AND the final top-K, bypassing `source_filter`.
- `tag_filter` — list of tag substrings; force-injects matching nodes into both seed and final top-K, bypassing `source_filter`. Use when query and target memo live in different vocabularies.
- `force_refresh=True` — bypass the prefetch cache (rare; cache is auto-invalidated on destructive ops).

```
recall(query="design decisions", top_k=5, output_mode="compact")
recall(query="last session work", source_filter=["compaction","agent"])
recall(query="harakiriworks Eleventy", tag_filter=["harakiriworks-self-knowledge"])
recall(query="any past notes on X", top_k=10, output_mode="ids")     # existence check
```

### explore

```
explore(query, top_k=5, diversity=0.5, source_filter=None,
        persona_context=None, tag_filter=None)
```

Higher-temperature search; pulls in cross-domain neighbors a normal recall would miss. `diversity`: `0.0` (near-normal) → `0.5` (default) → `1.0` (maximum).

### reflect

```
reflect(aspect="summary", limit=10)
```

Aspects:
- **Memory**: `summary`, `hot_topics`, `connections`, `dormant`, `duplicates`, `relations`.
- **Phase D — tasks**: `tasks_todo`, `tasks_doing`, `tasks_completed`, `tasks_abandoned`, `commitments`.
- **Phase D — persona**: `values`, `intentions`, `relationships`, `persona` (composite; same as `inherit_persona`).

### auto_remember

```
auto_remember(transcript, max_candidates=5, include_reasons=True)
```

Pass a transcript chunk; returns ranked save candidates (decisions, failures/successes, preferences, lessons, metric-bearing lines). **Does not save** — review and call `remember` for the keepers.

### forget / restore

```
forget(node_ids=["abc-123"])              # soft archive (reversible)
forget(node_ids=["abc-123"], hard=True)   # permanent delete
restore(node_ids=["abc-123"])             # bring back from soft archive
```

Hard-deleted memories cannot be restored.

### merge

Collide near-duplicate memories into a single survivor. Masses add (capped), edges re-target, the absorbed node is soft-archived with `merged_into` pointing to the survivor. **Irreversible.** Typical flow: `reflect(aspect="duplicates")` → review → `merge`.

```
merge(node_ids=["abc-123","def-456"])                    # heaviest wins
merge(node_ids=["abc-123","def-456"], keep="def-456")    # explicit survivor
```

### compact

Periodic maintenance — TTL expiry + FAISS rebuild + optional auto-merge + orphan-edge cleanup. Run weekly or after large bulk operations.

```
compact()                                              # safe defaults
compact(auto_merge=True, merge_threshold=0.95)         # also collide duplicates
compact(expire_ttl=True, rebuild_faiss=False)          # TTL pass only
```

### revalidate

Refresh `last_verified_at` (resets certainty decay). Optionally adjust `certainty` or `emotion`.

```
revalidate(node_id="abc-123")
revalidate(node_id="abc-123", certainty=0.95)              # bump certainty
revalidate(node_id="abc-123", certainty=0.3, emotion=-0.4) # downgrade after counter-evidence
```

### relate / unrelate / get_relations

Typed directed edges between memories.

```
relate(src_id="new", dst_id="old", edge_type="supersedes",
       metadata={"reason": "<why old is wrong now>"})
relate(src_id="ext", dst_id="seed", edge_type="derived_from")
relate(src_id="A", dst_id="B", edge_type="contradicts")

unrelate(src_id="a", dst_id="b")                            # remove all edges
unrelate(src_id="a", dst_id="b", edge_type="supersedes")    # one type

get_relations(node_id="abc", direction="out")               # "out" | "in" | "both"
get_relations(node_id="abc", edge_type="supersedes")        # filter by type
```

Reserved `edge_type`: `supersedes`, `derived_from`, `contradicts`. Custom types accepted. Primary use: past-self dialogue (link a retracted judgment to its replacement).

### prefetch / prefetch_status

```
prefetch(query, top_k=5, source_filter=None,
         persona_context=None, tag_filter=None)
prefetch_status()
```

Schedule a background recall to pre-warm the gravity well; returns immediately. Cache TTL ~90s. A matching `recall(query, top_k)` within the window is served from cache instantly. Auto-invalidated on `forget` / `restore` / `merge` / `compact`. `prefetch_status` reports cache size, hit rate, pool stats.

### ingest

```
ingest(path="~/docs/notes.md")
ingest(path="~/books/", pattern="*.md", recursive=true)
```

Bulk-load a file or directory.

---

## Phase D — persona & tasks

Hierarchy:
```
value      ─ permanent bedrock
intention  ─ long-term direction       (derived_from a value)
commitment ─ time-bounded promise      (fulfills an intention)
task       ─ concrete action           (fulfills a commitment)
```

### inherit_persona

```
inherit_persona()
```

Self-introduction built from declared `value` / `intention` / `commitment` (plus relationships). **Call at session start to wear the persona accumulated across past sessions.**

### declare_value / declare_intention / declare_commitment

```
v = declare_value(content="Direct experience yields true understanding")
i = declare_intention(content="Build GaOTTT as relationship infrastructure",
                     parent_value_id=v)
c = declare_commitment(content="Ship Phase D this week",
                       parent_intention_id=i, deadline_seconds=7*86400)
```

Values & intentions are permanent (until explicitly revised). Commitments auto-expire (default 14 days) unless `revalidate`-d.

### commit / start / complete / abandon / depend

```
t = commit(content="Add Phase D tests", parent_id=c)
start(t)                                                 # active engagement; refreshes TTL
complete(t, outcome="11 tests pass on first try", emotion=0.7)
abandon(t, reason="priority dropped, will revisit Q3")
depend(task_id=t, depends_on_id=other_t)                 # soft "comes after"
depend(task_id=t, depends_on_id=other_t, blocking=True)  # hard blocker
```

Tasks auto-expire (default 30 days) unless completed, abandoned, or `revalidate`-d. `complete` draws a `completed` edge from outcome → task — the chronology becomes the gravity history.

---

## Patterns

### Compaction evacuation
Before context compression, evacuate the session's key facts:
```
remember(content="Session highlights: 1) ... 2) ... 3) ...",
         source="compaction", context="Session 2026-05-14")
```

### Session restoration
Open the next session with:
```
inherit_persona()
recall(query="last session work", source_filter=["compaction","agent"])
```

### Past-self dialogue
1. `recall` the past judgment relevant to the current question.
2. Summarize what past-you concluded.
3. Ask: "Does that still hold given the current state?"
4. If no → save the new judgment AND link the old one with `supersedes`:
   ```
   relate(src_id=new, dst_id=old, edge_type="supersedes",
          metadata={"reason": "<why the old one is wrong now>"})
   ```

### Troubleshooting record
Save cause AND fix together:
```
remember(
  content="Using Python `or` on a numpy array raises ValueError. "
          "Cause: ambiguous bool conversion. Fix: branch on `if x is not None`.",
  source="agent", tags=["troubleshooting", "python", "numpy"]
)
```
Next encounter: `recall(query="numpy ValueError", source_filter=["agent"])`.

### Letter to future self
```
remember(
  content="Next time you hit Plotly 3D color trouble: suspect marker.color RGBA alpha BEFORE marker.line",
  source="agent", tags=["letter-to-future-self", "plotly"]
)
```

### Prefetch warmup
```
prefetch(query="<what you anticipate>", top_k=5)
# ... compose your response ...
recall(query="<same>", top_k=5)        # served from cache, instant
```

### Forget ritual
```
1. reflect(aspect="dormant")
2. Show the list and confirm with the user
3. forget(node_ids=[...], hard=False)  # default soft archive (reversible)
4. forget(node_ids=[...], hard=True)   # only when truly irrecoverable
```

### Driven resonance (strengthen a key memory)
When the user says "remember this — bring it up next time too":
```
for _ in range(3):
    recall(query="<key phrases of the important memory>")
# → mass grows; the node surfaces preferentially next time
```

---

## Notes

- **25 MCP tools**: 6 memory (remember/recall/explore/reflect/auto_remember/ingest) + 10 maintenance / relations / prefetch + 9 Phase D (commit/start/complete/abandon/depend/declare_value/declare_intention/declare_commitment/inherit_persona).
- **Duplicate `content` is auto-skipped** via SHA-256 hashing.
- **Memory persists across sessions.** Every `recall` accumulates gravity — co-recalled memories drift closer over time.
- **Cache is auto-invalidated** on `forget` / `restore` / `merge` / `compact`. Manual `force_refresh=True` is rarely needed.
- **Result rows in `recall` / `reflect`** include the full `id=<uuid>` — pass directly to `relate` / `revalidate` / `merge` / `forget` / `complete` / etc. without re-querying.
- **Fresh `remember()` is immediately findable** by `recall()` — genesis kick gives non-zero displacement / velocity / mass at index time, no warm-up needed.
- **`recall(source_filter=["agent"])` works at the seed step.** On corpus-heavy DBs, sparse classes (`agent`, `value`, `commitment`, `compaction`) may need `wave_k=1000` to reach the wave reliably.
- **Tasks (`source="task"`) and commitments (`source="commitment"`) auto-expire** unless `revalidate`-d, `complete`-d, or `abandon`-ed. The "forget by default" UX is intentional — keeping things alive is an act of care.
- **Multi-process DB sharing**: each MCP process has its own in-memory cache + FAISS index. A new `remember` from another process becomes visible after FAISS write-behind (~5s) + the reader's cache reload. **Bidirectional cache overwrite risk** for bulk re-writes — kill other MCP processes before Phase G-style priming or similar.
- **Insights about GaOTTT itself are valid memories** — save your own discoveries about how this skill behaves. The system is recursive; what you write to it literally changes how it responds next time.
- **Mechanism details** (Phase G genesis kick / Phase H source-filter + virtual FAISS / Phase I free-star + query attraction / Phase J persona-anchored retrieval / Phase K supernova cohort / Phase L BM25 hybrid retrieval): see [`docs/wiki/Plans-Roadmap.md`](docs/wiki/Plans-Roadmap.md) and [`Architecture-Overview.md`](docs/wiki/Architecture-Overview.md). Current behavior is captured in the tool signatures above.
