from dataclasses import dataclass


@dataclass
class GERConfig:
    # Embedding
    model_name: str = "cl-nagoya/ruri-v3-310m"
    embedding_dim: int = 768
    batch_size: int = 32

    # Retrieval
    top_k: int = 10

    # Scoring
    alpha: float = 0.05       # Mass boost scaling
    delta: float = 0.01       # Temporal decay rate
    gamma: float = 0.5        # Temperature scaling
    rho: float = 0.1          # Graph propagation weight

    # Mass update
    eta: float = 0.05         # Mass growth rate
    m_max: float = 50.0       # Mass saturation limit

    # Co-occurrence graph
    edge_threshold: int = 5   # Co-occurrence count to form edge
    edge_decay: float = 0.97  # Edge weight decay factor
    prune_threshold: float = 0.5  # Edge removal threshold
    max_degree: int = 20      # Per-node edge cap

    # Similarity history
    sim_buffer_size: int = 20  # Ring buffer size

    # Storage
    db_path: str = "ger_rag.db"
    faiss_index_path: str = "ger_rag.faiss"

    # Write-behind
    flush_interval_seconds: float = 5.0
    flush_threshold: int = 100
