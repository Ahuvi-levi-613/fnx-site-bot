import json

import pytest

from fnx_bot.answer.llm import LLMClient, LLMError, LLMResponse
from fnx_bot.answer.pipeline import AnswerPipeline, Source
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


def test_retriever_strips_hebrew_prefix_letter():
    # Chunk uses the bare word "מרפסת"; query uses the prefixed form "במרפסת" ("on the balcony").
    # Without stripping the ב prefix these are two different tokens that would never overlap.
    chunk = {"id": "c3", "url": "https://www.fnx.co.il/balcony", "page_title": "כיסוי מרפסת",
             "heading_path": [], "text": "נזק שנגרם למרפסת מכוסה בפוליסה", "chunk_index": 0,
             "crawled_at": "d", "area": "apartment"}
    r = HybridRetriever(FakeEmbedder(), FakeStore([]), chunks=[chunk])
    out = r.search("נגרם נזק במרפסת שלי")
    assert any(x["id"] == "c3" for x in out)


# --- prompt --------------------------------------------------------------------


def test_build_user_prompt_includes_source_and_question():
    passages = [{"url": "https://x/1", "page_title": "t", "heading_path": "a > b", "text": "content"}]
    p = build_user_prompt("שאלה?", passages)
    assert "https://x/1" in p and "content" in p and "שאלה?" in p


def test_build_user_prompt_no_passages():
    p = build_user_prompt("שאלה?", [])
    assert "שאלה?" in p and "לא נמצאו" in p


def test_build_user_prompt_includes_history_when_given():
    passages = [{"url": "https://x/1", "page_title": "t", "heading_path": "", "text": "content"}]
    history = [{"question": "שאלה ישנה", "answer": "תשובה ישנה"}]
    p = build_user_prompt("שאלה חדשה", passages, history=history)
    assert "שאלה ישנה" in p and "תשובה ישנה" in p and "שאלה חדשה" in p


def test_build_user_prompt_no_history_section_by_default():
    p = build_user_prompt("שאלה", [{"url": "u", "page_title": "t", "heading_path": "", "text": "c"}])
    assert "היסטוריי" not in p


def test_is_grounded_true_when_citing_a_given_url():
    assert is_grounded("תשובה טובה. https://www.fnx.co.il/car", {"https://www.fnx.co.il/car"})


def test_is_grounded_false_when_citing_other_url():
    assert not is_grounded("תשובה עם https://evil.example.com", {"https://www.fnx.co.il/car"})


def test_is_grounded_false_with_no_citation():
    assert not is_grounded("תשובה בלי קישור בכלל", {"https://www.fnx.co.il/car"})


def test_is_grounded_false_when_model_says_not_found_despite_a_url():
    # The model can cite a URL out of habit even while saying it doesn't actually know -
    # that must not count as grounded.
    text = "לא מצאתי מידע מדויק על כך באתר. https://www.fnx.co.il/car"
    assert not is_grounded(text, {"https://www.fnx.co.il/car"})


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
        llm=FakeLLM("STATUS: FOUND\nתשובה טובה. https://www.fnx.co.il/car"),
    )
    r = p.answer("שאלה")
    assert r.grounded is True
    assert r.sources == [Source(url="https://www.fnx.co.il/car", page_title="t")]


def test_pipeline_sources_only_lists_urls_the_model_actually_cited():
    candidates = [
        {"id": "c1", "url": "https://www.fnx.co.il/car", "text": "תוכן רכב", "score": 1.0,
         "page_title": "t", "heading_path": "h", "area": "car", "chunk_index": 0, "crawled_at": "d"},
        {"id": "c2", "url": "https://www.fnx.co.il/other", "text": "תוכן אחר", "score": 0.5,
         "page_title": "t2", "heading_path": "h2", "area": "car", "chunk_index": 0, "crawled_at": "d"},
    ]
    p = AnswerPipeline(
        retriever=FakeRetriever(candidates),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.9), RerankResult(index=1, relevance_score=0.8)]),
        llm=FakeLLM("STATUS: FOUND\nתשובה טובה. https://www.fnx.co.il/car"),  # cites only c1, not c2
    )
    r = p.answer("שאלה")
    assert r.grounded is True
    assert r.sources == [Source(url="https://www.fnx.co.il/car", page_title="t")]  # not c2


def test_pipeline_no_candidates_returns_not_on_site():
    p = AnswerPipeline(retriever=FakeRetriever([]), reranker=FakeReranker([]), llm=FakeLLM("x"))
    r = p.answer("שאלה")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE


# --- conversation memory (history) -------------------------------------------------


class FakeRetrieverByQuery:
    """Returns different candidates per exact query string, and records every query it got."""

    def __init__(self, by_query):
        self.by_query = by_query
        self.queries = []

    def search(self, query, k=10, area=None):
        self.queries.append(query)
        return self.by_query.get(query, [])


class RecordingReranker:
    def __init__(self, results):
        self._results = results
        self.calls = []  # (query, documents)

    def rerank(self, query, documents, top_n=None):
        self.calls.append((query, documents))
        return self._results


class RecordingLLM:
    def __init__(self, text):
        self._text = text
        self.prompts = []

    def generate(self, system, prompt):
        self.prompts.append(prompt)
        return LLMResponse(text=self._text, provider="fake")


CAR = {"id": "car1", "url": "https://www.fnx.co.il/car", "text": "תוכן רכב", "score": 1.0,
       "page_title": "רכב", "heading_path": "h", "area": "car", "chunk_index": 0, "crawled_at": "d"}
APARTMENT = {"id": "apt1", "url": "https://www.fnx.co.il/apartment", "text": "תוכן דירה", "score": 1.0,
             "page_title": "דירה", "heading_path": "h", "area": "apartment", "chunk_index": 0, "crawled_at": "d"}


def test_pipeline_history_searches_both_bare_and_combined_query():
    retriever = FakeRetrieverByQuery({
        "ומה עם רכב?": [CAR],
        "יש לי נזילה בדירה ומה עם רכב?": [APARTMENT],
    })
    reranker = RecordingReranker([RerankResult(index=0, relevance_score=0.9), RerankResult(index=1, relevance_score=0.9)])
    p = AnswerPipeline(retriever=retriever, reranker=reranker, llm=FakeLLM("STATUS: FOUND\nתשובה. https://www.fnx.co.il/car"))
    history = [{"question": "יש לי נזילה בדירה", "answer": "תשובה קודמת"}]

    p.answer("ומה עם רכב?", history=history)

    assert retriever.queries == ["ומה עם רכב?", "יש לי נזילה בדירה ומה עם רכב?"]
    _, documents = reranker.calls[0]
    assert len(documents) == 2  # union of both searches, deduped by id


def test_pipeline_no_history_searches_only_the_bare_question():
    retriever = FakeRetrieverByQuery({"שאלה": [CAR]})
    p = AnswerPipeline(
        retriever=retriever,
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.9)]),
        llm=FakeLLM("STATUS: FOUND\nתשובה. https://www.fnx.co.il/car"),
    )
    p.answer("שאלה")
    assert retriever.queries == ["שאלה"]


def test_pipeline_passes_history_into_llm_prompt():
    llm = RecordingLLM("תשובה טובה. https://www.fnx.co.il/car")
    p = AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.9)]),
        llm=llm,
    )
    history = [{"question": "שאלה קודמת", "answer": "תשובה קודמת"}]
    p.answer("שאלה חדשה", history=history)
    assert "שאלה קודמת" in llm.prompts[0] and "תשובה קודמת" in llm.prompts[0]


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
        llm=FakeLLM("STATUS: FOUND\nתשובה בלי קישור בכלל"),
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


# --- explicit STATUS line: "no answer" must never come with sources -------------------

from fnx_bot.answer.prompt import parse_status  # noqa: E402


@pytest.mark.parametrize("line", ["STATUS: FOUND", "**STATUS: FOUND**", "status:found", "  STATUS : FOUND  "])
def test_parse_status_found_variants(line):
    assert parse_status(f"{line}\nתשובה") == ("FOUND", "תשובה")


@pytest.mark.parametrize("line", ["STATUS: NOT_FOUND", "**STATUS:** NOT_FOUND", "STATUS: NOT FOUND"])
def test_parse_status_not_found_variants(line):
    assert parse_status(f"{line}\nאין מידע")[0] == "NOT_FOUND"


def test_parse_status_missing_line():
    assert parse_status("תשובה בלי שורת סטטוס https://www.fnx.co.il/car") == (
        None, "תשובה בלי שורת סטטוס https://www.fnx.co.il/car")


def _pipeline_with(llm_text):
    return AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.9)]),
        llm=FakeLLM(llm_text),
    )


def test_pipeline_not_found_status_drops_sources_even_with_a_valid_url():
    # The 2026-10-23 eval case: a soft "no direct answer" that still cited real passage URLs.
    r = _pipeline_with("STATUS: NOT_FOUND\nאין כאן תשובה ישירה. https://www.fnx.co.il/car").answer("שאלה")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE and r.sources == []


def test_pipeline_missing_status_is_treated_as_not_found():
    r = _pipeline_with("תשובה טובה. https://www.fnx.co.il/car").answer("שאלה")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE and r.sources == []


def test_pipeline_found_status_line_is_not_shown_to_the_user():
    r = _pipeline_with("STATUS: FOUND\nתשובה טובה. https://www.fnx.co.il/car").answer("שאלה")
    assert r.grounded is True and "STATUS" not in r.text and r.text.startswith("תשובה טובה")


def test_pipeline_found_but_soft_refusal_wording_still_refuses():
    # Backup net: model says FOUND yet the text admits there's no info.
    r = _pipeline_with("STATUS: FOUND\nהקטעים לא סופקו לי עם פרטים. https://www.fnx.co.il/car").answer("שאלה")
    assert r.grounded is False and r.sources == []


# --- natural refusals: the model's own words, but only if they pass the safety check ----------

from fnx_bot.answer.prompt import CONTACT_URL, safe_refusal  # noqa: E402

NATURAL = "על מזג האוויר אני לא יכולה לעזור, אני כאן בשביל שאלות על הביטוחים של הפניקס. נוסעת לחו\"ל? אשמח לספר על ביטוח נסיעות 😊"


def test_safe_refusal_keeps_a_short_natural_reply_and_adds_contact():
    out = safe_refusal(NATURAL)
    assert out.startswith(NATURAL) and out.endswith(CONTACT_URL)


@pytest.mark.parametrize("reply", [
    "באתר אין מידע, אבל מחר צפויות 25 מעלות.",       # a number = content slipped in
    "אפשר לבדוק ב-https://weather.example.com",      # a URL
    "צריך לפנות למייל info@example.com",             # an email
    "יש כרגע תקלה, נסו שוב.",                         # the UI reads this word as an outage
    "משפט. " * 4,                                     # too many sentences
    "א" * 300,                                        # too long
    "",                                               # empty
])
def test_safe_refusal_rejects_anything_that_looks_like_content(reply):
    assert safe_refusal(reply) is None


def test_pipeline_not_found_shows_the_natural_refusal_without_sources():
    r = _pipeline_with(f"STATUS: NOT_FOUND\n{NATURAL}").answer("מה מזג האוויר מחר?")
    assert r.grounded is False and r.sources == []
    assert r.text.startswith(NATURAL) and r.text.endswith(CONTACT_URL)


def test_pipeline_not_found_with_unsafe_reply_falls_back_to_fixed_message():
    r = _pipeline_with("STATUS: NOT_FOUND\nאין באתר, אבל מחר 25 מעלות.").answer("מה מזג האוויר מחר?")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE and r.sources == []


class RecordingFakeLLM(FakeLLM):
    def __init__(self, text):
        super().__init__(text)
        self.prompts = []

    def generate(self, system, prompt):
        self.prompts.append(prompt)
        return super().generate(system, prompt)


def test_pipeline_low_relevance_still_asks_the_model_with_no_passages():
    llm = RecordingFakeLLM(f"STATUS: NOT_FOUND\n{NATURAL}")
    p = AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.01)]),
        llm=llm,
    )
    r = p.answer("מה מזג האוויר מחר?")
    assert "https://www.fnx.co.il/car" not in llm.prompts[0]  # the low-relevance passage isn't sent
    assert r.grounded is False and r.sources == [] and r.text.startswith(NATURAL)


def test_pipeline_low_relevance_found_claim_cannot_become_an_answer():
    # No passages were given, so even a "FOUND" with a real-looking site URL has nothing to cite.
    p = AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.01)]),
        llm=FakeLLM("STATUS: FOUND\nמחר יהיה חם. https://www.fnx.co.il/car"),
    )
    r = p.answer("מה מזג האוויר מחר?")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE and r.sources == []


def test_pipeline_low_relevance_llm_outage_is_a_plain_refusal_not_an_outage():
    p = AnswerPipeline(
        retriever=FakeRetriever(CANDIDATE),
        reranker=FakeReranker([RerankResult(index=0, relevance_score=0.01)]),
        llm=FailingLLM(),
    )
    r = p.answer("מה מזג האוויר מחר?")
    assert r.grounded is False and r.text == NOT_ON_SITE_MESSAGE


def test_pipeline_forgotten_status_plus_refusal_wording_never_shows_sources():
    # Reviewer's case: the model forgets STATUS *and* says "not found" while citing a real URL.
    r = _pipeline_with("לא מצאתי מידע על כך. https://www.fnx.co.il/car").answer("שאלה")
    assert r.grounded is False and r.sources == [] and r.text == NOT_ON_SITE_MESSAGE
