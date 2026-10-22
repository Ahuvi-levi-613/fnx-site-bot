"""Hybrid retrieval: Chroma semantic search + keyword overlap over data/chunks.jsonl.

A pure embedding search can miss an exact term (a product or claim-type name) that doesn't
move the vector much; keyword overlap catches that case, so results are a union of both.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from ..config import DATA_DIR
from ..index.store import ChromaStore

_WORD_RE = re.compile(r"[א-תa-zA-Z0-9]+")
# Hebrew inseparable prepositions/conjunctions (ב-ה-ו-ל-מ-ש-כ) attach directly to the next word
# ("דירה" / "בדירה" / "לדירה" are all "apartment"), so a plain word match misses them.
_PREFIX_LETTERS = set("בהולמשכ")


class Embedder(Protocol):
    def embed_query(self, question: str) -> list[float]: ...


def _tokenize(text: str) -> set[str]:
    tokens = set()
    for w in _WORD_RE.findall(text):
        w = w.lower()
        tokens.add(w)
        if len(w) > 2 and w[0] in _PREFIX_LETTERS:
            tokens.add(w[1:])  # also index/match the word with one leading prefix letter stripped
    return tokens


def load_chunks(path: Path | None = None) -> list[dict]:
    path = path or DATA_DIR / "chunks.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _as_result(c: dict, score: float) -> dict:
    return {
        "id": c["id"],
        "text": c["text"],
        "score": score,
        "url": c["url"],
        "page_title": c.get("page_title", ""),
        "heading_path": " > ".join(c.get("heading_path", [])),
        "area": c.get("area", ""),
        "chunk_index": c.get("chunk_index", 0),
        "crawled_at": c.get("crawled_at", ""),
    }


class HybridRetriever:
    def __init__(self, embedder: Embedder, store: ChromaStore, chunks: list[dict] | None = None):
        self.embedder = embedder
        self.store = store
        self.chunks = chunks if chunks is not None else load_chunks()
        self._chunk_tokens = [(_tokenize(f"{c.get('page_title', '')} {c['text']}"), c) for c in self.chunks]

    def _keyword_search(self, query: str, k: int, area: str | None) -> list[dict]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        scored = []
        for tokens, c in self._chunk_tokens:
            if area and c.get("area") != area:
                continue
            overlap = len(q_tokens & tokens)
            if overlap:
                scored.append((overlap / len(q_tokens), c))
        scored.sort(key=lambda x: -x[0])
        return [_as_result(c, score) for score, c in scored[:k]]

    def search(self, query: str, k: int = 10, area: str | None = None) -> list[dict]:
        """Union of semantic and keyword hits, deduped by chunk id (semantic result kept on overlap)."""
        semantic = self.store.query(self.embedder.embed_query(query), k=k, area=area)
        keyword = self._keyword_search(query, k, area)
        merged: dict[str, dict] = {}
        for r in semantic + keyword:
            merged.setdefault(r["id"], r)
        return list(merged.values())
