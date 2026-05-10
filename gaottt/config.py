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
    max_displacement_norm: float = 0.3 # Max L2 norm of displacement vector

    # Gravity wave propagation
    wave_initial_k: int = 3            # Initial FAISS top-k for seed nodes
    wave_max_depth: int = 2            # Maximum recursion depth
    wave_base_k: int = 2              # Minimum neighbors per node
    wave_mass_scale: float = 2.0       # Mass-to-top-k scaling factor
    wave_max_node_k: int = 10          # Maximum neighbors per node
    wave_attenuation: float = 0.3      # Force decay per depth level
    wave_mass_attenuation_factor: float = 0.5  # Mass-based attenuation reduction
    wave_boost_weight: float = 0.05    # Wave force weight in final score

    # Gravitational radius — derived from a = G * m / r²
    wave_gravity_a_min: float = 0.1         # Minimum gravitational acceleration threshold

    # Co-occurrence black hole
    bh_mass_scale: float = 0.5             # BH mass = scale * log(1 + Σ edge_weight)
    bh_gravity_G: float = 0.0              # BH gravity constant (0 = use gravity_G)

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
    # a real chance of being reached. Default 500 is calibrated for 20-30k
    # corpora with sparse target classes (~1-2% of total) — at 1.7% sparsity
    # the expected agent-class count in top-500 is ~8.5, robust against
    # the all-zero outcome that hit at 200 (expected ~3.4).
    wave_k_with_filter: int = 500

    # Phase H — Wave seed redesign (H.3 Mass-aware seed boosting):
    # FAISS raw cosine top-K seed alone misses heavy nodes that sit
    # slightly outside top cosine. We pull a wider pool, rerank by
    # `raw + α * log(1+mass)`, then take the top initial_k. With α=0
    # the behaviour is identical to legacy raw cosine top-K seeding,
    # so existing setups can opt out by setting it to 0.
    wave_seed_mass_alpha: float = 0.1
    wave_seed_pool_size: int = 50

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
    dream_interval_seconds: float = 60.0   # tick cadence; 0 disables loop
    dream_batch_size: int = 5              # quiet nodes revisited per tick
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
