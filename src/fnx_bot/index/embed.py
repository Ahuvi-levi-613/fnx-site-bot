"""Gemini Embedding 2 client: batch requests, retry on quota errors, local cache."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

API = "https://generativelanguage.googleapis.com/v1beta/models"


class EmbedError(Exception):
    pass


def document_text(title: str, text: str) -> str:
    # gemini-embedding-2 takes the task as a text prefix (no taskType field).
    return f"title: {title or 'none'} | text: {text}"


def query_text(question: str) -> str:
    return f"task: search result | query: {question}"


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dim: int | None = None,
        cache_path: Path | None = None,
        batch_size: int = 50,
        session: requests.Session | None = None,
    ):
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = model or os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-2")
        self.dim = dim or int(os.getenv("GEMINI_EMBED_DIM", "768"))
        self.batch_size = batch_size
        self.session = session or requests.Session()
        self.cache_path = cache_path
        self._cache: dict[str, list[float]] = {}
        if cache_path and cache_path.exists():
            for ln in cache_path.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    row = json.loads(ln)
                    self._cache[row["k"]] = row["v"]

    def _key(self, text: str) -> str:
        return hashlib.sha1(f"{self.model}|{self.dim}|{text}".encode()).hexdigest()

    def _post(self, method: str, body: dict, tries: int = 6) -> dict:
        if not self.api_key:
            raise EmbedError("Missing GEMINI_API_KEY in .env")
        url = f"{API}/{self.model}:{method}"
        for i in range(tries):
            try:
                r = self.session.post(url, headers={"x-goog-api-key": self.api_key}, json=body, timeout=60)
            except requests.RequestException as e:
                if i == tries - 1:
                    raise EmbedError(str(e)) from e
            else:
                if r.ok:
                    return r.json()
                if r.status_code != 429 and r.status_code < 500:
                    raise EmbedError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
                if i == tries - 1:
                    raise EmbedError(f"Gemini HTTP {r.status_code} after {tries} tries (quota?)")
                wait = r.headers.get("Retry-After")
                if wait and wait.isdigit():
                    time.sleep(int(wait))
                    continue
            time.sleep(min(60, 2 ** (i + 1)))
        raise EmbedError("unreachable")

    def _request(self, text: str) -> dict:
        return {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "output_dimensionality": self.dim,
        }

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed already-prefixed texts, using the cache for ones seen before."""
        keys = [self._key(t) for t in texts]
        todo = [i for i, k in enumerate(keys) if k not in self._cache]
        for start in range(0, len(todo), self.batch_size):
            idx = todo[start : start + self.batch_size]
            body = {"requests": [self._request(texts[i]) for i in idx]}
            vecs = [e["values"] for e in self._post("batchEmbedContents", body)["embeddings"]]
            if len(vecs) != len(idx):
                raise EmbedError("Gemini returned a different number of embeddings than requested")
            new = {keys[i]: v for i, v in zip(idx, vecs)}
            self._cache.update(new)
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with self.cache_path.open("a", encoding="utf-8") as f:
                    for k, v in new.items():
                        f.write(json.dumps({"k": k, "v": v}) + "\n")
        return [self._cache[k] for k in keys]

    def embed_query(self, question: str) -> list[float]:
        return self.embed_many([query_text(question)])[0]
