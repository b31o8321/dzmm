import pytest
from langchain_core.embeddings import Embeddings

from dzmm.service.world_rag import index_world, is_indexed


class _FakeEmbedder(Embeddings):
    """Deterministic fake embedder — no network calls."""
    DIM = 8

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def _vec(self, text: str) -> list[float]:
        h = hash(text) % (10 ** 8)
        return [(h >> i & 0xFF) / 255.0 for i in range(self.DIM)]


def test_index_world_creates_chroma_dir(tmp_path, monkeypatch):
    import dzmm.service.world_rag as wr
    monkeypatch.setattr(wr, "APP_DIR", tmp_path)

    content = "世界是一片浩瀚的草原。" * 20  # > 800 chars
    index_world(1, content, "http://unused", _embedder=_FakeEmbedder())

    assert is_indexed(1, app_dir=tmp_path)


def test_index_world_is_idempotent(tmp_path, monkeypatch):
    import dzmm.service.world_rag as wr
    monkeypatch.setattr(wr, "APP_DIR", tmp_path)

    content = "a" * 1000
    embedder = _FakeEmbedder()
    index_world(1, content, "http://unused", _embedder=embedder)
    # calling again must not raise
    index_world(1, content, "http://unused", _embedder=embedder)

    assert is_indexed(1, app_dir=tmp_path)


def test_is_indexed_false_when_no_dir(tmp_path):
    assert not is_indexed(99, app_dir=tmp_path)
