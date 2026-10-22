"""Cohere Rerank client (SPEC rerank step)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

API_URL = "https://api.cohere.com/v2/rerank"


class RerankError(Exception):
    pass


@dataclass
class RerankResult:
    index: int  # position in the documents list passed to rerank()
    relevance_score: float


class CohereReranker:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        session: requests.Session | None = None,
    ):
        self.api_key = (api_key if api_key is not None else os.getenv("COHERE_API_KEY", "")).strip()
        self.model = model or os.getenv("COHERE_RERANK_MODEL", "rerank-v3.5")
        self.session = session or requests.Session()

    def rerank(self, query: str, documents: list[str], top_n: int | None = None, tries: int = 5) -> list[RerankResult]:
        """Rerank documents by relevance to query. Results are sorted best-first."""
        if not self.api_key:
            raise RerankError("Missing COHERE_API_KEY in .env")
        if not documents:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {"model": self.model, "query": query, "documents": documents}
        if top_n is not None:
            body["top_n"] = top_n
        for i in range(tries):
            try:
                r = self.session.post(API_URL, headers=headers, json=body, timeout=30)
            except requests.RequestException as e:
                if i == tries - 1:
                    raise RerankError(str(e)) from e
            else:
                if r.ok:
                    results = r.json()["results"]
                    return [RerankResult(x["index"], x["relevance_score"]) for x in results]
                if r.status_code != 429 and r.status_code < 500:
                    raise RerankError(f"Cohere HTTP {r.status_code}: {r.text[:300]}")
                if i == tries - 1:
                    raise RerankError(f"Cohere HTTP {r.status_code} after {tries} tries (rate limit?)")
            time.sleep(min(30, 2 ** (i + 1)))
        raise RerankError("unreachable")
