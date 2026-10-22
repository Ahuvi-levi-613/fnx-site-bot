import json
import sys

import pytest

from fnx_bot.index.embed import EmbedError, GeminiEmbedder, VoyageEmbedder, document_text, query_text


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.ok = status < 400
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    """Answers batchEmbedContents with one 3-dim vector per request; can fail first with 429."""

    def __init__(self, fail_first=0):
        self.calls, self.fail_first = [], fail_first

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, json))
        if self.fail_first:
            self.fail_first -= 1
            return Resp(429, headers={"Retry-After": "0"})
        n = len(json["requests"])
        return Resp(200, {"embeddings": [{"values": [float(i), 1.0, 0.0]} for i in range(n)]})


def test_prefixes_for_gemini_embedding_2():
    assert document_text("ביטוח דירה", "טקסט") == "title: ביטוח דירה | text: טקסט"
    assert document_text("", "טקסט") == "title: none | text: טקסט"
    assert query_text("מה עושים?") == "task: search result | query: מה עושים?"


def test_batches_cache_and_retry(tmp_path):
    s = FakeSession(fail_first=1)
    cache = tmp_path / "cache.jsonl"
    e = GeminiEmbedder(api_key="k", model="gemini-embedding-2", dim=3, cache_path=cache, batch_size=2, batch_pause=0, session=s)
    vecs = e.embed_many(["a", "b", "c"])
    assert len(vecs) == 3
    assert len(s.calls) == 3  # 429, then 2 batches (2 + 1)
    url, body = s.calls[-1]
    assert url.endswith("/gemini-embedding-2:batchEmbedContents")
    assert body["requests"][0]["output_dimensionality"] == 3

    # A new embedder reads the cache: nothing is sent again.
    s2 = FakeSession()
    e2 = GeminiEmbedder(api_key="k", model="gemini-embedding-2", dim=3, cache_path=cache, session=s2)
    assert e2.embed_many(["a", "b", "c"]) == vecs and s2.calls == []


def test_missing_key():
    with pytest.raises(EmbedError):
        GeminiEmbedder(api_key="", session=FakeSession()).embed_many(["a"])


class FakeVoyageSession:
    """Answers /v1/embeddings with one 3-dim vector per input, index fields reversed (to check
    we sort by index rather than assume response order); can fail first with 429."""

    def __init__(self, fail_first=0):
        self.calls, self.fail_first = [], fail_first

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, json))
        if self.fail_first:
            self.fail_first -= 1
            return Resp(429, headers={"Retry-After": "0"})
        n = len(json["input"])
        data = [{"embedding": [float(i), 1.0, 0.0], "index": i} for i in range(n)]
        return Resp(200, {"data": list(reversed(data))})


def test_voyage_batches_cache_and_retry(tmp_path):
    s = FakeVoyageSession(fail_first=1)
    cache = tmp_path / "cache.jsonl"
    e = VoyageEmbedder(api_key="k", model="voyage-3.5", dim=3, cache_path=cache, batch_size=2, batch_pause=0, session=s)
    vecs = e.embed_many(["a", "b", "c"], input_type="document")
    assert len(vecs) == 3
    assert vecs[0] == [0.0, 1.0, 0.0] and vecs[1] == [1.0, 1.0, 0.0]  # order preserved despite reversed response
    assert len(s.calls) == 3  # 429, then 2 batches (2 + 1)
    url, body = s.calls[-1]
    assert url == "https://api.voyageai.com/v1/embeddings"
    assert body["model"] == "voyage-3.5" and body["input_type"] == "document" and body["output_dimension"] == 3

    # A new embedder reads the cache: nothing is sent again.
    s2 = FakeVoyageSession()
    e2 = VoyageEmbedder(api_key="k", model="voyage-3.5", dim=3, cache_path=cache, session=s2)
    assert e2.embed_many(["a", "b", "c"], input_type="document") == vecs and s2.calls == []


def test_voyage_query_uses_input_type():
    s = FakeVoyageSession()
    e = VoyageEmbedder(api_key="k", dim=3, session=s)
    e.embed_query("מה עושים?")
    assert s.calls[0][1]["input_type"] == "query"


def test_missing_key_voyage():
    with pytest.raises(EmbedError):
        VoyageEmbedder(api_key="", session=FakeVoyageSession()).embed_many(["a"])


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chromadb's Rust client segfaults under pytest on Windows (not in a plain script); runs fine in CI on Linux.",
)
def test_chroma_rebuild_and_query(tmp_path):
    pytest.importorskip("chromadb")
    from fnx_bot.index.store import ChromaStore

    chunks = [
        {"id": "c1", "url": "https://www.fnx.co.il/car", "page_title": "רכב", "heading_path": ["רכב", "תביעות"],
         "text": "תביעת רכב", "chunk_index": 0, "crawled_at": "d", "area": "car"},
        {"id": "c2", "url": "https://www.fnx.co.il/dira", "page_title": "דירה", "heading_path": ["דירה"],
         "text": "נזקי מים", "chunk_index": 0, "crawled_at": "d", "area": "apartment"},
    ]
    store = ChromaStore(path=tmp_path / "chroma")
    assert store.rebuild(chunks, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]) == 2
    assert store.rebuild(chunks, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]) == 2  # rebuild replaces, no duplicates
    top = store.query([0.9, 0.1, 0.0], k=1)[0]
    assert top["id"] == "c1" and top["url"] == "https://www.fnx.co.il/car" and top["heading_path"] == "רכב > תביעות"
    assert store.query([0.9, 0.1, 0.0], k=1, area="apartment")[0]["id"] == "c2"
