from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer


class RuriEmbedder:
    QUERY_PREFIX = "検索クエリ: "
    DOCUMENT_PREFIX = "検索文書: "

    def __init__(self, model_name: str = "cl-nagoya/ruri-v3-310m", batch_size: int = 32):
        self._model = SentenceTransformer(model_name)
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        return self._model.get_sentence_embedding_dimension()

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        prefixed = [self.DOCUMENT_PREFIX + t for t in texts]
        embeddings = self._model.encode(
            prefixed,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embeddings.astype(np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        prefixed = self.QUERY_PREFIX + text
        embedding = self._model.encode(
            [prefixed],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embedding.astype(np.float32)
