"""Day 2 answer pipeline: hybrid retrieval -> rerank -> site-only prompt -> LLM -> source check.

SPEC core rule: the bot answers only from crawled content and cites the source URL.
No source, no answer -> NOT_ON_SITE_MESSAGE with contact options instead.
"""
from __future__ import annotations

from dataclasses import dataclass

from .llm import LLMClient, LLMError
from .prompt import (
    NOT_ON_SITE_MESSAGE,
    SERVICE_UNAVAILABLE_MESSAGE,
    SYSTEM_PROMPT,
    build_user_prompt,
    cited_urls,
    is_grounded,
    parse_status,
    safe_refusal,
)
from .rerank import CohereReranker, RerankError
from .retrieve import HybridRetriever

RERANK_TOP_N = 5
MIN_RELEVANCE = 0.1  # below this, treat the top rerank hit as noise, not an actual match


@dataclass
class Source:
    url: str
    page_title: str


@dataclass
class AnswerResult:
    text: str
    sources: list[Source]
    grounded: bool  # False = no answer from the site (a refusal or outage message), never with sources
    # Which LLM wrote the reply ("gemini:<model>" / "groq"), or None if no model was used
    # (fixed message before or instead of a model call). Lets an eval tell Gemini answers from fallback ones.
    provider: str | None = None


class AnswerPipeline:
    def __init__(self, retriever: HybridRetriever, reranker: CohereReranker, llm: LLMClient):
        self.retriever = retriever
        self.reranker = reranker
        self.llm = llm

    def answer(self, question: str, area: str | None = None, history: list[dict] | None = None) -> AnswerResult:
        # Search with the question alone AND combined with the previous one, then merge: a
        # follow-up like "ומה עם רכב?" can be too bare to retrieve well on its own, but
        # combining it with the prior question can drag in that question's own topic too -
        # the union covers both without needing an extra LLM call to rewrite the question.
        queries = [question]
        if history:
            queries.append(f"{history[-1]['question']} {question}")

        candidates_by_id: dict[str, dict] = {}
        for q in queries:
            for c in self.retriever.search(q, k=10, area=area):
                candidates_by_id.setdefault(c["id"], c)
        candidates = list(candidates_by_id.values())
        if not candidates:
            return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False)

        rerank_query = queries[-1]  # the most context-rich variant (combined, if there was history)
        try:
            ranked = self.reranker.rerank(rerank_query, [c["text"] for c in candidates], top_n=RERANK_TOP_N)
        except RerankError:
            return AnswerResult(text=SERVICE_UNAVAILABLE_MESSAGE, sources=[], grounded=False)
        top = [candidates[r.index] for r in ranked if r.relevance_score >= MIN_RELEVANCE]

        # Even with no relevant passages the model is still asked, with none attached, so an
        # off-topic question gets a natural "not something I can help with" instead of a canned
        # line. With no passages there's nothing it can cite, so it can't come back as an answer.
        try:
            response = self.llm.generate(SYSTEM_PROMPT, build_user_prompt(question, top, history=history))
        except LLMError:
            if not top:
                return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False)
            return AnswerResult(text=SERVICE_UNAVAILABLE_MESSAGE, sources=[], grounded=False)
        # Only an explicit "STATUS: FOUND" counts as an answer. NOT_FOUND shows the model's own
        # short refusal if it passes safe_refusal(); otherwise, or with a missing/garbled status
        # line, the fixed message. Either way: no sources - a non-answer never comes with citations.
        provider = response.provider
        status, text = parse_status(response.text)
        if status == "NOT_FOUND":
            return AnswerResult(text=safe_refusal(text) or NOT_ON_SITE_MESSAGE, sources=[], grounded=False,
                                provider=provider)
        if status != "FOUND":
            return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False, provider=provider)
        allowed = {p["url"] for p in top}
        if not is_grounded(text, allowed):
            return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False, provider=provider)
        # Only the pages the model actually cited, not every candidate it was handed -
        # the SPEC rule is "the link points to the page the answer came from".
        cited = {u for u in cited_urls(text) if u in allowed}
        seen: set[str] = set()
        sources = []
        for p in top:
            if p["url"] in cited and p["url"] not in seen:
                seen.add(p["url"])
                sources.append(Source(url=p["url"], page_title=p.get("page_title", "")))
        sources.sort(key=lambda s: s.url)
        return AnswerResult(text=text, sources=sources, grounded=True, provider=provider)
