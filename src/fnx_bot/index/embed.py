"""Embedding clients: batch requests, retry on quota errors, local cache.

GeminiEmbedder (Gemini Embedding 2) is the SPEC primary; its free tier caps at 1,000
requests/day, so VoyageEmbedder (Voyage AI, SPEC backup) is what build_index.py uses.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests

API = "https://generativelanguage.googleapis.com/v1beta/models"
VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"
# Free-tier quota errors put the real cooldown in the message body, not a Retry-After header,
# e.g. "...Please retry in 11.799435817s."
_RETRY_IN_RE = re.compile(r"retry in (\d+(?:\.\d+)?)s", re.IGNORECASE)


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
        batch_pause: float = 36.0,  # 50/batch, so ~83 req/min, safely under the 100/min free-tier cap
        session: requests.Session | None = None,
    ):
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = model or os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-2")
        self.dim = dim or int(os.getenv("GEMINI_EMBED_DIM", "768"))
        self.batch_size = batch_size
        self.batch_pause = batch_pause
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

    def _post(self, method: str, body: dict, tries: int = 8) -> dict:
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
                m = _RETRY_IN_RE.search(r.text or "")
                if m:
                    time.sleep(float(m.group(1)) + 1)  # +1s safety margin
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
            if start > 0:
                time.sleep(self.batch_pause)  # stay under the free-tier requests/min quota
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


class VoyageEmbedder:
    """Voyage AI embeddings (SPEC backup). Multilingual, no text-prefix trick needed:
    document vs. query is set via the input_type field instead.

    Defaults are sized for an account with no payment method on file, which Voyage caps
    at 3 requests/min and 10K tokens/min (the 200M free tokens still apply either way;
    adding a card only raises the throughput cap, e.g. to 8M TPM / 2000 RPM for voyage-3.5).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dim: int | None = None,
        cache_path: Path | None = None,
        batch_size: int = 20,
        batch_pause: float = 21.0,  # 3 req/min cap -> >=20s apart
        session: requests.Session | None = None,
    ):
        self.api_key = (api_key if api_key is not None else os.getenv("VOYAGE_API_KEY", "")).strip()
        self.model = model or os.getenv("VOYAGE_EMBED_MODEL", "voyage-3.5")
        self.dim = dim or int(os.getenv("VOYAGE_EMBED_DIM", "1024"))
        self.batch_size = batch_size
        self.batch_pause = batch_pause
        self.session = session or requests.Session()
        self.cache_path = cache_path
        self._cache: dict[str, list[float]] = {}
        if cache_path and cache_path.exists():
            for ln in cache_path.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    row = json.loads(ln)
                    self._cache[row["k"]] = row["v"]

    def _key(self, text: str, input_type: str) -> str:
        return hashlib.sha1(f"{self.model}|{self.dim}|{input_type}|{text}".encode()).hexdigest()

    def _post(self, body: dict, tries: int = 8) -> dict:
        if not self.api_key:
            raise EmbedError("Missing VOYAGE_API_KEY in .env")
        headers = {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        for i in range(tries):
            try:
                r = self.session.post(VOYAGE_API_URL, headers=headers, json=body, timeout=60)
            except requests.RequestException as e:
                if i == tries - 1:
                    raise EmbedError(str(e)) from e
            else:
                if r.ok:
                    return r.json()
                if r.status_code != 429 and r.status_code < 500:
                    raise EmbedError(f"Voyage HTTP {r.status_code}: {r.text[:300]}")
                if i == tries - 1:
                    raise EmbedError(f"Voyage HTTP {r.status_code} after {tries} tries (rate limit?)")
                wait = r.headers.get("Retry-After")
                if wait and wait.replace(".", "", 1).isdigit():
                    time.sleep(float(wait))
                    continue
            time.sleep(min(60, 2 ** (i + 1)))
        raise EmbedError("unreachable")

    def embed_many(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        """Embed texts, using the cache for ones seen before."""
        keys = [self._key(t, input_type) for t in texts]
        todo = [i for i, k in enumerate(keys) if k not in self._cache]
        for start in range(0, len(todo), self.batch_size):
            if start > 0:
                time.sleep(self.batch_pause)  # stay under the requests/min cap
            idx = todo[start : start + self.batch_size]
            body = {
                "input": [texts[i] for i in idx],
                "model": self.model,
                "input_type": input_type,
                "output_dimension": self.dim,
            }
            data = sorted(self._post(body)["data"], key=lambda e: e["index"])
            if len(data) != len(idx):
                raise EmbedError("Voyage returned a different number of embeddings than requested")
            new = {keys[i]: e["embedding"] for i, e in zip(idx, data)}
            self._cache.update(new)
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with self.cache_path.open("a", encoding="utf-8") as f:
                    for k, v in new.items():
                        f.write(json.dumps({"k": k, "v": v}) + "\n")
        return [self._cache[k] for k in keys]

    def embed_query(self, question: str) -> list[float]:
        return self.embed_many([question], input_type="query")[0]
