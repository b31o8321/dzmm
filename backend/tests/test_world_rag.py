from langchain_core.embeddings import Embeddings

from dzmm.service.world_rag import get_world_md, index_world, is_indexed, retrieve_world_context


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


def test_delete_world_index_removes_chroma_dir(tmp_path, monkeypatch):
    """After delete_world_index, the persist directory is gone — embeddings
    no longer outlive the deleted World row."""
    import dzmm.service.world_rag as wr
    monkeypatch.setattr(wr, "APP_DIR", tmp_path)

    content = "世界是一片浩瀚的草原。" * 20
    index_world(7, content, "http://unused", _embedder=_FakeEmbedder())
    assert is_indexed(7, app_dir=tmp_path)

    wr.delete_world_index(7, app_dir=tmp_path)
    assert not is_indexed(7, app_dir=tmp_path)


def test_delete_world_index_silent_when_missing(tmp_path):
    """delete_world_index on never-indexed world is a no-op."""
    from dzmm.service.world_rag import delete_world_index
    delete_world_index(12345, app_dir=tmp_path)  # must not raise


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


def test_retrieve_returns_relevant_chunk(tmp_path, monkeypatch):
    import dzmm.service.world_rag as wr
    monkeypatch.setattr(wr, "APP_DIR", tmp_path)

    content = (
        "草原地区：一片广阔的绿色平原，马群在此奔驰，风吹草低见牛羊。" * 15
        + "\n\n"
        + "地下城区：黑暗的迷宫，充满了骷髅和宝藏，冒险者趋之若鹜。" * 15
    )
    embedder = _FakeEmbedder()
    index_world(2, content, "http://unused", _embedder=embedder)

    result = retrieve_world_context(2, "草原上的马", "http://unused",
                                    _embedder=embedder, app_dir=tmp_path)
    assert "草原" in result


def test_get_world_md_returns_full_text_when_short(tmp_path):
    short_content = "小世界"  # < 800 chars
    result = get_world_md(1, short_content, "query", "http://unused", app_dir=tmp_path)
    assert result == short_content


def test_get_world_md_returns_full_text_when_not_indexed(tmp_path):
    long_content = "a" * 1000
    # world_id=99 is never indexed in tmp_path
    result = get_world_md(99, long_content, "query", "http://unused", app_dir=tmp_path)
    assert result == long_content


def test_get_world_md_uses_rag_when_indexed(tmp_path, monkeypatch):
    import dzmm.service.world_rag as wr
    monkeypatch.setattr(wr, "APP_DIR", tmp_path)

    # Use enough content so top-k chunks are much shorter than the full text
    content = "龙族世界：古老的龙族统治着这片大陆，他们居住在高山之巅的城堡之中。" * 100
    embedder = _FakeEmbedder()
    index_world(3, content, "http://unused", _embedder=embedder)

    result = get_world_md(3, content, "龙族的历史", "http://unused",
                          _embedder=embedder, app_dir=tmp_path)
    assert "龙族" in result
    assert len(result) < len(content)


def test_get_world_md_returns_full_text_when_ollama_url_none(tmp_path, monkeypatch):
    import dzmm.service.world_rag as wr
    monkeypatch.setattr(wr, "APP_DIR", tmp_path)

    content = "x" * 1000
    embedder = _FakeEmbedder()
    index_world(4, content, "http://unused", _embedder=embedder)

    # ollama_url=None should skip RAG and return full text
    result = get_world_md(4, content, "query", None, app_dir=tmp_path)
    assert result == content
