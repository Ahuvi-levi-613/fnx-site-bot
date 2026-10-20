"""Chroma vector store on local disk (data/chroma). No account needed."""
from __future__ import annotations

from pathlib import Path

from ..config import DATA_DIR

COLLECTION = "fnx_site"


def _client(path: Path):
    import chromadb  # imported here so the crawl works without it installed

    return chromadb.PersistentClient(path=str(path))


def chunk_metadata(c: dict) -> dict:
    # Chroma metadata values must be str / int / float / bool.
    return {
        "url": c["url"],
        "page_title": c.get("page_title", ""),
        "heading_path": " > ".join(c.get("heading_path", [])),
        "area": c.get("area", ""),
        "chunk_index": int(c.get("chunk_index", 0)),
        "crawled_at": c.get("crawled_at", ""),
    }


class ChromaStore:
    def __init__(self, path: Path = DATA_DIR / "chroma", name: str = COLLECTION):
        self.client = _client(path)
        self.name = name

    def collection(self):
        return self.client.get_or_create_collection(
            self.name, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    def rebuild(self, chunks: list[dict], embeddings: list[list[float]], batch: int = 500) -> int:
        """Replace the whole collection, so pages removed from the site don't linger."""
        if self.name in [c.name if hasattr(c, "name") else c for c in self.client.list_collections()]:
            self.client.delete_collection(self.name)
        col = self.collection()
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            col.add(
                ids=[c["id"] for c in part],
                documents=[c["text"] for c in part],
                metadatas=[chunk_metadata(c) for c in part],
                embeddings=embeddings[i : i + batch],
            )
        return col.count()

    def query(self, embedding: list[float], k: int = 5, area: str | None = None) -> list[dict]:
        res = self.collection().query(
            query_embeddings=[embedding],
            n_results=k,
            where={"area": area} if area else None,
            include=["documents", "metadatas", "distances"],
        )
        return [
            {"id": i, "text": d, "score": 1 - dist, **m}
            for i, d, m, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])
        ]
