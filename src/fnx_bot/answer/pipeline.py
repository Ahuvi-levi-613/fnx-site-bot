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
    grounded: bool  # False means NOT_ON_SITE_MESSAGE was returned


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
        if not top:
            return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False)

        try:
            response = self.llm.generate(SYSTEM_PROMPT, build_user_prompt(question, top, history=history))
        except LLMError:
            return AnswerResult(text=SERVICE_UNAVAILABLE_MESSAGE, sources=[], grounded=False)
        allowed = {p["url"] for p in top}
        if not is_grounded(response.text, allowed):
            return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False)
        # Only the pages the model actually cited, not every candidate it was handed -
        # the SPEC rule is "the link points to the page the answer came from".
        cited = {u for u in cited_urls(response.text) if u in allowed}
        seen: set[str] = set()
        sources = []
        for p in top:
            if p["url"] in cited and p["url"] not in seen:
                seen.add(p["url"])
                sources.append(Source(url=p["url"], page_title=p.get("page_title", "")))
        sources.sort(key=lambda s: s.url)
        return AnswerResult(text=response.text, sources=sources, grounded=True)
