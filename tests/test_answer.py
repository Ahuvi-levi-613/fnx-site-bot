import json

import pytest

from fnx_bot.answer.llm import LLMClient, LLMError, LLMResponse
from fnx_bot.answer.pipeline import AnswerPipeline
from fnx_bot.answer.prompt import NOT_ON_SITE_MESSAGE, SERVICE_UNAVAILABLE_MESSAGE, build_user_prompt, is_grounded
from fnx_bot.answer.rerank import CohereReranker, RerankError, RerankResult
from fnx_bot.answer.retrieve import HybridRetriever


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}
        self.ok = status < 400
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


# --- CohereReranker ---------------------------------------------------------


class FakeRerankSession:
    def __init__(self, fail_first=0):
        self.calls, self.fail_first = [], fail_first

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, json))
        if self.fail_first:
            self.fail_first -= 1
            return Resp(429)
        docs = json["documents"]
        # Score the last document highest, to check index/order is preserved correctly.
        results = sorted(
            ({"index": i, "relevance_score": (i + 1) / len(docs)} for i in range(len(docs))),
            key=lambda r: -r["relevance_score"],
        )
        return Resp(200, {"results": results})


def test_rerank_sorts_best_first():
    s = FakeRerankSession()
    r = CohereReranker(api_key="k", session=s)
    out = r.rerank("מה זה?", ["doc a", "doc b", "doc c"])
    assert [x.index for x in out] == [2, 1, 0]
    url, body = s.calls[0]
    assert url == "https://api.cohere.com/v2/rerank"
    assert body["model"] == "rerank-v3.5" and body["query"] == "מה זה?"


def test_rerank_retries_on_429():
    s = FakeRerankSession(fail_first=1)
    r = CohereReranker(api_key="k", session=s)
    out = r.rerank("q", ["a", "b"])
    assert len(out) == 2 and len(s.calls) == 2


def test_rerank_empty_documents_skips_call():
    s = FakeRerankSession()
    assert CohereReranker(api_key="k", session=s).rerank("q", []) == []
    assert s.calls == []


def test_rerank_missing_key():
    with pytest.raises(RerankError):
        CohereReranker(api_key="", session=FakeRerankSession()).rerank("q", ["a"])


# --- LLMClient ---------------------------------------------------------------


class FakeLLMSession:
    """status_by_provider: {"gemini": 200, "groq": 429, ...} - which HTTP status each
    provider's URL returns; a missing entry means that provider isn't called."""

    def __init__(self, status_by_provider):
        self.status_by_provider = status_by_provider
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        if "generativelanguage" in url:
            provider = "gemini"
        elif "groq" in url:
            provider = "groq"
        else:
            provider = "openrouter"
        self.calls.append(provider)
        status = self.status_by_provider[provider]
        if status != 200:
            return Resp(status)
        if provider == "gemini":
            return Resp(200, {"candidates": [{"content": {"parts": [{"text": f"answer from {provider}"}]}}]})
        return Resp(200, {"choices": [{"message": {"content": f"answer from {provider}"}}]})


def test_llm_uses_gemini_first():
    s = FakeLLMSession({"gemini": 200})
    c = LLMClient(gemini_api_key="k", groq_api_key="k", openrouter_api_key="k", retry_pause=0, session=s)
    r = c.generate("system", "question")
    assert r.provider == "gemini" and r.text == "answer from gemini"
    assert s.calls == ["gemini"]


def test_llm_falls_back_on_429():
    s = FakeLLMSession({"gemini": 429, "groq": 429, "openrouter": 200})
    c = LLMClient(gemini_api_key="k", groq_api_key="k", openrouter_api_key="k", retry_pause=0, session=s)
    r = c.generate("system", "question")
    assert r.provider == "openrouter"
    assert s.calls == ["gemini", "groq", "openrouter"]


def test_llm_missing_key_falls_through():
    s = FakeLLMSession({"groq": 200})
    c = LLMClient(gemini_api_key="", groq_api_key="k", openrouter_api_key="", retry_pause=0, session=s)
    r = c.generate("system", "question")
    assert r.provider == "groq" and s.calls == ["groq"]


def test_llm_all_providers_fail():
    s = FakeLLMSession({"gemini": 429, "groq": 429, "openrouter": 500})
    c = LLMClient(gemini_api_key="k", groq_api_key="k", openrouter_api_key="k", retry_pause=0, session=s)
    with pytest.raises(LLMError):
        c.generate("system", "question")


# --- HybridRetriever -----------------------------------------------------------


class FakeEmbedder:
    def embed_query(self, question):
        return [0.0]


class FakeStore:
    def __init__(self, results):
        self._results = results

    def query(self, embedding, k=5, area=None):
        return [r for r in self._results if not area or r["area"] == area][:k]


SAMPLE_CHUNKS = [
    {"id": "c1", "url": "https://www.fnx.co.il/car", "page_title": "ביטוח רכב", "heading_path": ["רכב", "תביעות"],
     "text": "איך מגישים תביעת רכב בעקבות תאונה", "chunk_index": 0, "crawled_at": "d", "area": "car"},
    {"id": "c2", "url": "https://www.fnx.co.il/apartment", "page_title": "ביטוח דירה", "heading_path": ["דירה"],
     "text": "נזקי מים בדירה - איך מגישים תביעה", "chunk_index": 0, "crawled_at": "d", "area": "apartment"},
]


def test_retriever_finds_keyword_match_semantic_missed():
    r = HybridRetriever(FakeEmbedder(), FakeStore([]), chunks=SAMPLE_CHUNKS)
    out = r.search("נזקי מים בדירה")
    assert any(x["id"] == "c2" for x in out)


def test_retriever_merges_and_dedupes_semantic_and_keyword():
    semantic_hit = {"id": "c1", "text": "...", "score": 0.9, "url": "u", "page_title": "p", "heading_path": "h",
                     "area": "car", "chunk_index": 0, "crawled_at": "d"}
    r = HybridRetriever(FakeEmbedder(), FakeStore([semantic_hit]), chunks=SAMPLE_CHUNKS)
    out = r.search("תביעת רכב תאונה")  # also matches c1 by keyword -> must not appear twice
    ids = [x["id"] for x in out]
    assert ids.count("c1") == 1
    assert "c2" not in ids


def test_retriever_keyword_search_respects_area():
    r = HybridRetriever(FakeEmbedder(), FakeStore([]), chunks=SAMPLE_CHUNKS)
    out = r.search("תביעה", area="apartment")
    assert out and all(x["area"] == "apartment" for x in out)


# --- prompt --------------------------------------------------------------------


def test_build_user_prompt_includes_source_and_question():
    passages = [{"url": "https://x/1", "page_title": "t", "heading_path": "a > b", "text": "content"}]
    p = build_user_prompt("שאלה?", passages)
    assert "https://x/1" in p and "content" in p and "שאלה?" in p


def test_build_user_prompt_no_passages():
    p = build_user_prompt("שאלה?", [])
    assert "שאלה?" in p and "לא נמצאו" in p


def test_is_grounded_true_when_citing_a_given_url():
    assert is_grounded("תשובה טובה. https://www.fnx.co.il/car", {"https://www.fnx.co.il/car"})


def test_is_grounded_false_when_citing_other_url():
    assert not is_grounded("תשובה עם https://evil.example.com", {"https://www.fnx.co.il/car"})


def test_is_grounded_false_with_no_citation():
    assert not is_grounded("תשובה בלי קישור בכלל", {"https://www.fnx.co.il/car"})


# --- AnswerPipeline --------------------------------------------------------------


class FakeRetriever:
    def __init__(self, candidates):
        self._candidates = candidates

    def search(self, query, k=10, area=None):
        return self._candidates


class FakeReranker:
    def __init__(self, results):
        self._results = results

    def rerank(self, query, documents, top_n=None):
        return self._results


class FakeLLM:
    def __init__(self, text):
        self._text = text

    def generate(self, system, prompt):
        return LLMResponse(text=self._text, provider="fake")


CANDIDATE = [{"id": "c1", "url": "https://www.fnx.co.il/car", "text": "תוכן", "score": 1.0, "page_title": "t",
              "heading_path": "h", "area": "car", "chunk_index": 0, "crawled_at": "d"}]


def test_pipeline_returns_grounded_answer():
    p = AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.9)]),
        llm=FakeLLM("תשובה טובה. https://www.fnx.co.il/car"),
    )
    r = p.answer("שאלה")
    assert r.grounded is True
    assert r.sources == ["https://www.fnx.co.il/car"]


def test_pipeline_no_candidates_returns_not_on_site():
    p = AnswerPipeline(retriever=FakeRetriever([]), reranker=FakeReranker([]), llm=FakeLLM("x"))
    r = p.answer("שאלה")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE


def test_pipeline_low_relevance_returns_not_on_site():
    p = AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.01)]),
        llm=FakeLLM("should not be called"),
    )
    r = p.answer("שאלה")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE


def test_pipeline_ungrounded_llm_answer_returns_not_on_site():
    p = AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.9)]),
        llm=FakeLLM("תשובה בלי קישור בכלל"),
    )
    r = p.answer("שאלה")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE


class FailingReranker:
    def rerank(self, query, documents, top_n=None):
        raise RerankError("all tries failed")


class FailingLLM:
    def generate(self, system, prompt):
        raise LLMError("all providers failed")


def test_pipeline_rerank_outage_returns_service_unavailable():
    p = AnswerPipeline(retriever=FakeRetriever(CANDIDATE), reranker=FailingReranker(), llm=FakeLLM("x"))
    r = p.answer("שאלה")
    assert r.grounded is False and r.text == SERVICE_UNAVAILABLE_MESSAGE


def test_pipeline_llm_outage_returns_service_unavailable():
    p = AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.9)]),
        llm=FailingLLM(),
    )
    r = p.answer("שאלה")
    assert r.grounded is False and r.text == SERVICE_UNAVAILABLE_MESSAGE
