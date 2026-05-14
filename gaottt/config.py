import json
import logging
import math
import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path

logger = logging.getLogger(__name__)

# Config file locations (checked in order):
#   1. GAOTTT_CONFIG env var (legacy GER_RAG_CONFIG accepted with deprecation warning)
#   2. ~/.config/gaottt/config.json  (Linux/macOS)
#      %APPDATA%/gaottt/config.json  (Windows)
#   3. Legacy ~/.config/ger-rag/config.json (fallback for migrating users)
_CONFIG_FILE_PATHS = []

_env_config = os.environ.get("GAOTTT_CONFIG") or os.environ.get("GER_RAG_CONFIG")
if os.environ.get("GER_RAG_CONFIG") and not os.environ.get("GAOTTT_CONFIG"):
    logger.warning(
        "GER_RAG_CONFIG is deprecated; use GAOTTT_CONFIG. "
        "Continuing with the legacy variable."
    )
if _env_config:
    _CONFIG_FILE_PATHS.append(Path(_env_config))

if sys.platform == "win32":
    _appdata = os.environ.get("APPDATA", "")
    if _appdata:
        _CONFIG_FILE_PATHS.append(Path(_appdata) / "gaottt" / "config.json")
        _CONFIG_FILE_PATHS.append(Path(_appdata) / "ger-rag" / "config.json")
else:
    _xdg = os.environ.get("XDG_CONFIG_HOME", "")
    _config_base = Path(_xdg) if _xdg else Path.home() / ".config"
    _CONFIG_FILE_PATHS.append(_config_base / "gaottt" / "config.json")
    _CONFIG_FILE_PATHS.append(_config_base / "ger-rag" / "config.json")


def _load_config_file() -> dict:
    """Load config overrides from JSON config file."""
    for path in _CONFIG_FILE_PATHS:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                logger.info("Loaded config from %s", path)
                return data
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def _legacy_data_dir_default() -> Path:
    """Where the old GER-RAG default data directory would have been."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        return Path(local) / "ger-rag" if local else Path.home() / "ger-rag"
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "ger-rag"


def _default_data_dir() -> str:
    """Resolve data directory.

    Priority:
      1. GAOTTT_DATA_DIR env var (legacy GER_RAG_DATA_DIR accepted with warning)
      2. "data_dir" in config file
      3. Platform default:
         - Linux/macOS: ~/.local/share/gaottt/
         - Windows:     %LOCALAPPDATA%/gaottt/

    Backward compatibility: if no env/config override is set and the
    new platform default is empty, but a legacy ger-rag/ directory exists
    with a real ger_rag.db, prefer the legacy path so existing users do
    not lose access to their memory. Run scripts/migrate-from-ger-rag.sh
    to move the data permanently.
    """
    env = os.environ.get("GAOTTT_DATA_DIR") or os.environ.get("GER_RAG_DATA_DIR")
    if os.environ.get("GER_RAG_DATA_DIR") and not os.environ.get("GAOTTT_DATA_DIR"):
        logger.warning(
            "GER_RAG_DATA_DIR is deprecated; use GAOTTT_DATA_DIR. "
            "Continuing with the legacy variable."
        )
    if env:
        p = Path(env)
    else:
        file_conf = _load_config_file()
        if "data_dir" in file_conf:
            p = Path(file_conf["data_dir"])
        elif sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "")
            p = Path(local) / "gaottt" if local else Path.home() / "gaottt"
        else:
            xdg = os.environ.get("XDG_DATA_HOME", "")
            base = Path(xdg) if xdg else Path.home() / ".local" / "share"
            p = base / "gaottt"

        legacy = _legacy_data_dir_default()
        if not (p / "gaottt.db").exists() and (legacy / "ger_rag.db").exists():
            logger.warning(
                "Detected legacy GER-RAG data at %s. "
                "Run scripts/migrate-from-ger-rag.sh to migrate to %s, "
                "or set GAOTTT_DATA_DIR explicitly.",
                legacy, p,
            )
            p = legacy

    p.mkdir(parents=True, exist_ok=True)
    return str(p)


@dataclass
class GaOTTTConfig:
    # Embedding
    model_name: str = "cl-nagoya/ruri-v3-310m"
    embedding_dim: int = 768
    batch_size: int = 32

    # Retrieval
    top_k: int = 5              # Results returned to LLM (presentation layer)

    # Scoring
    alpha: float = 0.05       # Mass boost scaling
    delta: float = 0.01       # Temporal decay rate
    gamma: float = 0.5        # Temperature scaling

    # Mass update
    eta: float = 0.05         # Mass growth rate
    m_max: float = 50.0       # Mass saturation limit

    # Co-occurrence graph
    edge_threshold: int = 5   # Co-occurrence count to form edge
    edge_decay: float = 0.97  # Edge weight decay factor
    prune_threshold: float = 0.5  # Edge removal threshold
    max_degree: int = 20      # Per-node edge cap

    # Gravitational displacement
    gravity_G: float = 0.01            # Gravitational constant
    gravity_eta: float = 0.005         # Displacement learning rate
    gravity_epsilon: float = 1e-6      # Zero-division guard
    displacement_decay: float = 0.995  # Per-step displacement decay
    displacement_age_delta: float = 0.005  # Access-age based decay rate
    max_displacement_norm: float = 1e6 # L2 norm cap on displacement. Phase I (2026-05-11): default raised from 0.3 → 1e6 (effectively ∞). Hooke (orbital_anchor_strength) + displacement_decay + orbital_max_velocity provide physical equilibrium around d ≈ (G·m/k)^(1/3) ≈ 0.8–3.0 without a hard cap. Set to a small value only as an emergency knob.

    # Phase I Stage 2 — Query-aware displacement (implicit kick)
    # Adds a 4th term to compute_acceleration: F_query = α · score · (q - pos);
    # a_query = F_query / m. Acts as the Hebbian gradient term in the TTT reading.
    # Hooke (orbital_anchor_strength) continues to pull back toward the raw
    # embedding anchor — query attraction is a transient force, not anchor
    # migration. Set to 0.0 as a clean roll-back.
    query_kick_strength: float = 0.01  # α — start small. Per-step accel is bounded by orbital_max_velocity (0.05), so α larger than ~0.05 saturates immediately. d=0.01 means ~10 recalls of the same query → ~0.1 drift toward query (Hooke equilibrium ~0.8).
    query_kick_enabled: bool = True    # Global off-switch; if False, skip the 4th term entirely.

    # Phase I Stage 3 — Mass-gated query attraction:
    # Adds a gate to the Stage 2 query-attraction term so that brand-new
    # (low-mass) nodes are protected by anchor (Hooke) until co-occurrence
    # structure forms. Without this gate, m_i ≈ 1.0 lets a single recall
    # trigger a near-full-α drift, producing the single-attractor pathology
    # (one node becoming top1 for many queries via positive feedback).
    #   gate = tanh(m_i / mass_anchor_threshold)
    #     mass=1, θ=3   → 0.32  (newly-added: heavily damped)
    #     mass=3, θ=3   → 0.76  (gate's characteristic point)
    #     mass=10, θ=3  → 0.997 (mature: nearly full)
    # Set θ=0.0 for clean rollback to Stage 2 behaviour (gate forced to 1.0).
    mass_anchor_threshold: float = 3.0

    # Phase J Stage 1 — Persona-anchored retrieval (graph traversal seed boost).
    # Boosts seed-pool ranking for nodes within N hops of an actively-declared
    # value / intention / commitment, via fulfills / derived_from edges.
    # Translates the Five-Layer persona layer into retrieval geometry — what
    # the user has declared as identity bends the gravity field at recall time.
    #   boosted_seed_score = raw_cosine + α_mass × log(1+mass)
    #                                   + α_persona × proximity
    #   proximity(node) = persona_hop_decay ** min_hop_distance(node, persona)
    #                     0.0 beyond persona_max_hop
    # Set persona_boost_enabled=False for clean rollback (boost path skipped).
    persona_boost_enabled: bool = True
    persona_boost_alpha: float = 0.5           # weight of proximity in seed rerank (5× wave_seed_mass_alpha — "context dominates mass" prior)
    persona_max_hop: int = 2                    # graph traversal limit (1=fulfills only, 2=+derived_from chain, 3+=indirect mixing risk)
    persona_hop_decay: float = 0.5              # per-hop decay (0.5: 1 hop=0.5, 2 hop=0.25)
    persona_active_ttl_seconds: float = 14 * 86400.0  # commitment TTL synchronized; intention/value are always active unless archived

    # Phase K Stage 1 — Stellar supernova cohort.
    # When `index_documents` receives a batch of size ≥ supernova_min_cohort_size,
    # the new nodes are treated as a single supernova event:
    #   (1) all pairs in the batch get a co-occurrence edge of weight
    #       supernova_initial_weight (event-driven, independent of Phase B's
    #       recall-based edge_threshold accumulation)
    #   (2) each node receives an outward initial velocity = α × (embedding - centroid),
    #       clamped to orbital_max_velocity
    # Applied AFTER Phase G genesis_kick (Phase G: existing-system binding;
    # Phase K: cohort-internal binding + explosion energy). Velocities are
    # added, not replaced — both physics co-exist.
    # Rationale: Phase J Stage 1 acceptance revealed that newly-remembered
    # cohorts have no mutual gravity, so they can't compete with mature
    # past-session clusters for FAISS top-K entry. Phase K fixes the physics
    # of memory creation rather than reranking after the fact.
    supernova_enabled: bool = True
    supernova_min_cohort_size: int = 2          # 1 件だけの remember は単独彗星 (Phase G で足りる)、2 件以上で発火
    supernova_initial_weight: float = 1.0       # 相互 edge の初期 weight (wave_seed_mass_alpha × log(1+w) で boost が効く)
    supernova_velocity_alpha: float = 0.03      # 爆発の運動量 α (orbital_max_velocity=0.05 以下に収まる)

    # Phase L Stage 1 — Hybrid retrieval (BM25 union seed).
    # Adds a third metric (BM25 lexical) alongside raw FAISS (semantic) and
    # virtual FAISS (semantic+history) to the seed pool. Lexical and semantic
    # are independent metric tensors — surface-form matches BM25 catches that
    # embedder cosine misses ("Eleventy Pipeline" → exact .eleventy.js match).
    # RRF fusion combines ranks scale-invariantly across the 3 indexes.
    #
    # Decision log (めいさん 2026-05-14):
    #   D1. bm25_score_mode default = "rrf" (Reciprocal Rank Fusion, k=60)
    #   D2. in-memory only in Stage 1 — startup rebuild from SQLite content;
    #       disk persistence is a future stage
    #   D3. tokenizer default = "trigram"; "sudachi" available as optional
    #       extra (uv pip install -e ".[bm25-sudachi]")
    #   D4. wave_neighbor 中の BM25 拡張なし — Stage 1 は seed pool 入場権のみ
    # Set hybrid_bm25_enabled=False for clean rollback (BM25 skipped entirely).
    hybrid_bm25_enabled: bool = True
    bm25_seed_k: int = 50                       # BM25 top-N drawn into the union pool
    bm25_k1: float = 1.5                        # Robertson-Sparck-Jones k1 (term-saturation)
    bm25_b: float = 0.75                        # length-normalization b
    bm25_score_mode: str = "rrf"                # "rrf" (default) | "weighted_sum"
    bm25_score_alpha: float = 0.5               # weighted_sum: BM25 normalized share; ignored for "rrf"
    rrf_k: int = 60                             # RRF rank-fusion constant (Cormack 2009 standard)
    bm25_tokenizer: str = "trigram"             # "trigram" (default) | "sudachi" (optional extra)

    # Gravity wave propagation
    wave_initial_k: int = 3            # Initial FAISS top-k for seed nodes
    # Phase M follow-up (2026-05-13): depth 2 → 3 to widen the displacement
    # update scope per recall (from ~20-50 nodes to ~60-150). Wave force
    # attenuation (`wave_attenuation`) still bounds the reach — depth 3
    # third-frontier nodes receive ~0.25 of seed force, deeper nodes drop
    # below the 0.001 force floor and are filtered automatically. Per-recall
    # latency cost +20-30% (mostly the extra per-frontier neighbor lookup).
    # Set to 2 to restore Phase L Stage 1 behaviour.
    wave_max_depth: int = 3            # Maximum recursion depth
    wave_base_k: int = 2              # Minimum neighbors per node
    wave_mass_scale: float = 2.0       # Mass-to-top-k scaling factor
    wave_max_node_k: int = 10          # Maximum neighbors per node
    wave_attenuation: float = 0.3      # Force decay per depth level
    wave_mass_attenuation_factor: float = 0.5  # Mass-based attenuation reduction
    wave_boost_weight: float = 0.05    # Wave force weight in final score

    # Gravitational radius — derived from a = G * m / r²
    wave_gravity_a_min: float = 0.1         # Minimum gravitational acceleration threshold

    # Co-occurrence black hole (Phase M: deprecated — replaced by mass-based BH).
    # Kept as fields so legacy configs and visualize_3d.py don't error; the
    # values are no longer consulted at runtime once
    # mass_bh_enabled=True. Removed in Phase M Stage 2.
    bh_mass_scale: float = 0.5             # deprecated; see mass_bh_*
    bh_gravity_G: float = 0.0              # deprecated; see mass_bh_*

    # Phase M Stage 1 — Mass conservation + mass-based BH.
    # (1) Mass conservation: when mass_conservation_enabled=True, the mass
    #     update in _update_simulation only counts force contributions from
    #     parent nodes that are NOT in the same original document
    #     (original_id) or supernova cohort (cohort_id). "Internal trade"
    #     between chunks of the same book no longer inflates mass —
    #     Articulation as Carrier (id=9a954c62) made literal.
    # (2) Mass-based BH: bh_factor(mass, θ, σ) = tanh((mass - θ) / σ),
    #     clamped to 0 below θ - 2σ. Heavy nodes become attractors
    #     gradually; no source-class branching (single rule for all).
    # θ/σ default to a placeholder; tuned after 1-2 weeks of observation
    # under the new rule (Phase M Stage 2). Set mass_bh_enabled=False to
    # disable the new attractor (force=0 from the mass-BH term).
    mass_conservation_enabled: bool = True
    mass_bh_enabled: bool = True
    mass_bh_theta: float = 5.0             # mass threshold for BH attractor onset
    mass_bh_sigma: float = 1.5             # tanh transition width

    # Orbital mechanics — velocity-based physics
    orbital_friction: float = 0.05          # Constant velocity friction per step
    orbital_friction_age_factor: float = 0.1  # Additional friction for unaccessed nodes
    orbital_max_velocity: float = 0.05      # Max L2 norm of velocity vector
    orbital_anchor_strength: float = 0.02   # Restoring force toward original position (Hooke's law)

    # Habituation & thermal escape
    saturation_rate: float = 0.2            # How fast nodes saturate (higher = faster)
    habituation_recovery_rate: float = 0.01 # Recovery from saturation per step
    thermal_escape_scale: float = 5000.0    # Temperature-based BH escape scaling

    # Similarity history
    sim_buffer_size: int = 20  # Ring buffer size

    # Storage — resolved to fixed data directory
    data_dir: str = field(default_factory=_default_data_dir)
    db_path: str = ""
    faiss_index_path: str = ""

    # Write-behind (cache → SQLite + FAISS index → disk)
    flush_interval_seconds: float = 5.0
    flush_threshold: int = 100
    # Periodic FAISS save: if non-zero, the engine spawns a background task
    # that calls faiss_index.save() every N seconds when dirty. Critical for
    # multi-process visibility — without this, brand-new `remember` lives
    # only in the writing process's in-memory FAISS until shutdown(), so
    # other processes' recall() never sees it. Set to 0 to disable.
    faiss_save_interval_seconds: float = 5.0

    # F4: TTL for ephemeral memory (source="hypothesis")
    default_hypothesis_ttl_seconds: float = 7 * 86400.0  # 7 days

    # F1: auto_remember heuristics
    auto_remember_default_max: int = 5
    auto_remember_min_chars: int = 12
    auto_remember_max_chars: int = 400

    # F7: emotional weight & certainty
    emotion_alpha: float = 0.04                       # Score weight per |emotion|
    certainty_alpha: float = 0.02                     # Score weight per certainty
    certainty_half_life_seconds: float = 30 * 86400.0 # 30 days half-life

    # F6: background prefetch
    prefetch_cache_size: int = 64                     # Max cached query results
    prefetch_ttl_seconds: float = 90.0                # Cache entry lifetime
    prefetch_max_concurrent: int = 4                  # Bounded async pool size

    # Source-filtered recall — seed pool expansion
    # When `source_filter` is set on `recall`, the default `wave_initial_k=3`
    # seeds from the densest cluster only, so sparse classes (agent / value /
    # intention / commitment / compaction) get squeezed out of the seed
    # pool entirely on corpus-heavy DBs (~10k+ entries). Boosting wave_k
    # for filtered queries oversamples seeds so the requested sources have
    # a real chance of being reached. Raised to 1000 (2026-05-12) after
    # production 23k-DB acceptance showed multiple queries reachable at 1000
    # that missed at 500; latency impact is negligible since source_filter
    # is only used for explicit sparse-class carve-out, not on hot paths.
    wave_k_with_filter: int = 1000

    # Phase H — Wave seed redesign (H.3 Mass-aware seed boosting):
    # FAISS raw cosine top-K seed alone misses heavy nodes that sit
    # slightly outside top cosine. We pull a wider pool, rerank by
    # `raw + α * log(1+mass)`, then take the top initial_k. With α=0
    # the behaviour is identical to legacy raw cosine top-K seeding,
    # so existing setups can opt out by setting it to 0.
    #
    # 2026-05-14 — set to 0.0 (Phase H Stage 1 disabled in seed step).
    # Diagnostic discovery: when Phase L Stage 1 hybrid retrieval is on
    # (hybrid_bm25_enabled=True, bm25_score_mode="rrf"), the `raw` value
    # passed to `_seed_boost` is an RRF score (~0.02-0.05 range), not a
    # raw cosine (0.0-1.0). The mass term `α × log(1+mass)` was tuned
    # for cosine scale, so in RRF mode mass dominates: e.g. heavy chunk
    # (RRF 0.018, mass 22) boost = 0.018+0.02·log(23) = 0.080, vs
    # book chunk (RRF 0.033, mass 1.4) boost = 0.033+0.02·log(2.4) =
    # 0.055 — semantically wrong chunk wins. Disabling the mass term
    # restores RRF as the seed-ranking signal (RRF already combines
    # raw cosine + virtual cosine + BM25 in a scale-invariant way).
    # The Phase H Stage 1 intent (heavy-node lift in seed) needs a
    # proper rescaling for RRF mode — tracked as Phase N tuning target.
    wave_seed_mass_alpha: float = 0.0
    wave_seed_pool_size: int = 50

    # Phase H Stage 3 — Density-aware dynamic wave_k:
    # Look at top_N raw cosine scores and decide if the query landed in
    # a "dense" cluster (top scores all close together) or a "sparse"
    # region (top-1 alone, then sharp dropoff). For sparse regions we
    # expand the effective seed pool up to `wave_initial_k_max` so that
    # the wave can reach further before mass / source rerank narrows it.
    # Set wave_dynamic_k_enabled=False to fall back to fixed initial_k.
    wave_dynamic_k_enabled: bool = True
    wave_density_window: int = 10            # how many top-N to inspect
    wave_density_threshold: float = 0.95     # tail/top ratio above this = "dense"
    wave_initial_k_max: int = 50             # cap for sparse-region expansion

    # Phase H Stage 4 — Virtual FAISS:
    # A second FAISS index built on virtual_pos (= raw embedding +
    # cached displacement, normalized). Phase G priming moves
    # displacement on every active node, but raw FAISS does not see
    # those updates — wave seeding therefore can't benefit from priming.
    # Virtual FAISS does. propagate_gravity_wave unions seeds from raw
    # and virtual indexes; if a node moved closer to the query through
    # priming, it can enter the seed pool via the virtual index even
    # when its raw cosine is far. Rebuilt at startup (if disk file is
    # missing) and on compact(rebuild_faiss=True). Saved on shutdown.
    virtual_faiss_enabled: bool = True
    virtual_faiss_index_path: str = ""
    # Phase H Stage 4 (cont., 2026-05-13) — Virtual FAISS write-behind:
    # Without this, virtual FAISS only refreshes at compact(rebuild_faiss=
    # True) or startup-when-missing, so Phase I/J query attraction and
    # genesis kicks accumulate in cache.displacement without ever being
    # visible to the next recall's seed pool. The loop checks
    # cache.virtual_faiss_dirty on a fixed cadence and triggers a full
    # rebuild + disk save when dirty. Default is 60s — slower than raw
    # FAISS's 5s because rebuild is O(N) over all active nodes; tune
    # down on small DBs, up on large ones. Set to 0 to disable.
    virtual_faiss_save_interval_seconds: float = 60.0
    # Phase H Stage 5 — Wave neighbor uses virtual FAISS:
    # Previously the seed pool unioned raw+virtual, but the wave's per-
    # frontier `search_by_id` only queried raw FAISS. That breaks the
    # "stars attract stars" design — the star is the virtual position
    # (raw + cached displacement), not the raw embedding. With this on,
    # neighbor expansion uses `virtual_faiss_index.search_by_id` (so a
    # node's virtual position drives who it pulls in), falling back to
    # raw when virtual_faiss_index is None or empty. Set to False to
    # restore the legacy raw-only neighbor search.
    wave_neighbor_use_virtual: bool = True

    # Phase D: persona & task TTL defaults
    default_task_ttl_seconds: float = 30 * 86400.0       # 30 日 (要 revalidate / complete / abandon)
    default_commitment_ttl_seconds: float = 14 * 86400.0  # 14 日

    # Phase G — Genesis kick: brand-new nodes receive a one-step gravitational
    # interaction with their top-K heavy neighbors at index time. Without this,
    # a fresh `remember` lands with mass=1.0 and zero displacement/velocity,
    # losing recall ranking to established clusters even when semantically
    # close. The kick gives the new node initial orbital state derived from
    # the same Newtonian formula the rest of the engine uses (no special-case
    # physics — just one step of update_orbital_state's force calculation).
    genesis_kick_enabled: bool = True
    genesis_kick_neighbor_k: int = 5      # heaviest K to include in the kick
    genesis_kick_pool_size: int = 50       # FAISS top-N pool to mass-rank from
    genesis_mass_boost_alpha: float = 0.5  # initial mass boost = α * |kick force|
    # Mass boost cap per kick — raw |acc| can spike for nodes near dense
    # cluster centers (observed max ~71 on the 23k production DB before
    # capping). Without a cap a single step could push mass close to m_max
    # in one go, which violates the "gradual accretion" feel of the model.
    genesis_mass_boost_cap: float = 1.0

    # Phase G — Dream consolidation (Stage 2): a background loop that picks
    # quiet (low-mass, idle) nodes and runs synthetic recalls against them
    # so they accumulate co-occurrence edges and gravity field updates over
    # time. Hippocampal-replay analog. Distinct from genesis kick — kick is
    # the single bound-to-orbit moment, dream is gradual tidal capture
    # spread across idle wall-clock.
    dream_enabled: bool = True
    # Phase M follow-up (2026-05-13): broaden the dream loop's coverage but
    # keep per-tick load small enough that foreground MCP / REST recalls
    # don't get starved. First-cut bump to 50 / 10s saturated the event
    # loop on a 24k DB (2.5s contiguous CPU burst per tick, foreground
    # MCP calls timed out), so we dial back to 10 / 30s and add an explicit
    # ``await asyncio.sleep(0)`` between candidates in ``_dream_loop`` to
    # yield to other tasks. Net: 20 source recalls/min × ~60-150 wave-
    # reached → ~24k full-corpus coverage in 15-30 minutes of background
    # work, ~2% sustained CPU, foreground recalls stay responsive.
    # Set interval=60s + batch=5 to restore Phase L Stage 1 cadence.
    dream_interval_seconds: float = 30.0   # tick cadence; 0 disables loop
    dream_batch_size: int = 10             # quiet nodes revisited per tick
    dream_mass_ceiling: float = 1.5        # only nodes with mass below this
    dream_min_idle_seconds: float = 300.0  # only nodes idle this long
    dream_top_k: int = 10                  # top_k for the synthetic recall

    def __post_init__(self):
        if not self.db_path:
            new_db = os.path.join(self.data_dir, "gaottt.db")
            legacy_db = os.path.join(self.data_dir, "ger_rag.db")
            if not os.path.exists(new_db) and os.path.exists(legacy_db):
                logger.warning(
                    "Using legacy ger_rag.db at %s; run scripts/migrate-from-ger-rag.sh to rename.",
                    legacy_db,
                )
                self.db_path = legacy_db
            else:
                self.db_path = new_db
        if not self.faiss_index_path:
            new_faiss = os.path.join(self.data_dir, "gaottt.faiss")
            legacy_faiss = os.path.join(self.data_dir, "ger_rag.faiss")
            if not os.path.exists(new_faiss) and os.path.exists(legacy_faiss):
                self.faiss_index_path = legacy_faiss
            else:
                self.faiss_index_path = new_faiss
        if not self.virtual_faiss_index_path:
            self.virtual_faiss_index_path = os.path.join(
                self.data_dir, "gaottt.virtual.faiss"
            )

    @classmethod
    def from_config_file(cls) -> "GaOTTTConfig":
        """Create GaOTTTConfig with overrides from config.json."""
        file_conf = _load_config_file()
        valid_fields = {f.name for f in fields(cls)}
        overrides = {k: v for k, v in file_conf.items() if k in valid_fields}
        return cls(**overrides)

    def compute_node_top_k(self, mass: float) -> int:
        """Compute per-node top-k based on mass."""
        k = self.wave_base_k + int(self.wave_mass_scale * math.log(1.0 + mass))
        return min(k, self.wave_max_node_k)

    def compute_effective_attenuation(self, mass: float) -> float:
        """Compute effective attenuation (high mass = slower decay = farther reach)."""
        mass_factor = math.log(1.0 + mass) / math.log(1.0 + self.m_max)
        return self.wave_attenuation * (1.0 - self.wave_mass_attenuation_factor * mass_factor)

    def compute_gravity_radius(self, mass: float) -> float:
        """Compute minimum cosine similarity for a node's gravity field.

        Derived from real gravitational physics:
          Gravitational acceleration: a = G * m / r²
          Gravity radius (where a drops below a_min): r = sqrt(G * m / a_min)
          Convert to cosine similarity: min_sim = 1 - G * m / (2 * a_min)

        Higher mass = lower threshold = wider gravitational reach.

        With G=0.01, a_min=0.1:
          mass=1   → min_sim=0.95 (dwarf — very close neighbors only)
          mass=10  → min_sim=0.50 (giant — moderate reach)
          mass=50  → min_sim=0.05 (supergiant — vast gravitational field)
        """
        r_squared = self.gravity_G * mass / self.wave_gravity_a_min
        min_sim = 1.0 - r_squared / 2.0
        return max(0.05, min(0.95, min_sim))
