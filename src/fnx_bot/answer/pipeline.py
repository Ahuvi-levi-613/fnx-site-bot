"""Day 2 answer pipeline: hybrid retrieval -> rerank -> site-only prompt -> LLM -> source check.

SPEC core rule: the bot answers only from crawled content and cites the source URL.
No source, no answer -> NOT_ON_SITE_MESSAGE with contact options instead.
"""
from __future__ import annotations

from dataclasses import dataclass

from .llm import LLMClient, LLMError
from .prompt import NOT_ON_SITE_MESSAGE, SERVICE_UNAVAILABLE_MESSAGE, SYSTEM_PROMPT, build_user_prompt, is_grounded
from .rerank import CohereReranker, RerankError
from .retrieve import HybridRetriever

RERANK_TOP_N = 5
MIN_RELEVANCE = 0.1  # below this, treat the top rerank hit as noise, not an actual match


@dataclass
class AnswerResult:
    text: str
    sources: list[str]
    grounded: bool  # False means NOT_ON_SITE_MESSAGE was returned


class AnswerPipeline:
    def __init__(self, retriever: HybridRetriever, reranker: CohereReranker, llm: LLMClient):
        self.retriever = retriever
        self.reranker = reranker
        self.llm = llm

    def answer(self, question: str, area: str | None = None) -> AnswerResult:
        candidates = self.retriever.search(question, k=10, area=area)
        if not candidates:
            return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False)

        try:
            ranked = self.reranker.rerank(question, [c["text"] for c in candidates], top_n=RERANK_TOP_N)
        except RerankError:
            return AnswerResult(text=SERVICE_UNAVAILABLE_MESSAGE, sources=[], grounded=False)
        top = [candidates[r.index] for r in ranked if r.relevance_score >= MIN_RELEVANCE]
        if not top:
            return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False)

        try:
            response = self.llm.generate(SYSTEM_PROMPT, build_user_prompt(question, top))
        except LLMError:
            return AnswerResult(text=SERVICE_UNAVAILABLE_MESSAGE, sources=[], grounded=False)
        allowed = {p["url"] for p in top}
        if not is_grounded(response.text, allowed):
            return AnswerResult(text=NOT_ON_SITE_MESSAGE, sources=[], grounded=False)
        return AnswerResult(text=response.text, sources=sorted(allowed), grounded=True)
