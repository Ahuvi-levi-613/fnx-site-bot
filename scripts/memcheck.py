#!/usr/bin/env python3
"""Check that the bot still fits the cloud server's memory (Render free = 512 MB).

  python scripts/memcheck.py              # uses data/chroma and data/chunks.jsonl
  python scripts/memcheck.py --limit 1024

Loads what the server loads (app, all chunks, Chroma) and runs a few searches with a random
query vector, so it needs no API keys and no network. Run it after every re-crawl.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

QUESTIONS = ["מה מכסה ביטוח חובה?", "איך מגישים תביעה על נזקי מים?", 'ביטוח נסיעות לחו"ל']
# Headroom for what this script doesn't load: uvicorn, live requests, the query cache.
MARGIN_MB = 100


def rss_mb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / 2**20
    except ImportError:
        import resource  # Linux / macOS only

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


class RandomEmbedder:
    def __init__(self, dim: int):
        self.dim = dim

    def embed_query(self, question: str) -> list[float]:
        return [random.random() for _ in range(self.dim)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=512, help="server memory in MB (default 512)")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    args = ap.parse_args()

    import fnx_bot.server.app  # noqa: F401  (FastAPI + app module, as the server does)
    from fnx_bot.answer.retrieve import HybridRetriever, load_chunks
    from fnx_bot.index.store import ChromaStore

    store = ChromaStore(path=args.data / "chroma")
    col = store.collection()
    sample = col.get(limit=1, include=["embeddings"])["embeddings"]
    dim = len(sample[0]) if sample is not None and len(sample) else 1024

    retriever = HybridRetriever(RandomEmbedder(dim), store, chunks=load_chunks(args.data / "chunks.jsonl"))
    for q in QUESTIONS:
        retriever.search(q, k=10)

    used = rss_mb()
    need = used + MARGIN_MB
    print(f"chunks: {len(retriever.chunks)}, vectors: {col.count()}")
    print(f"memory: {used:.0f} MB (+{MARGIN_MB} MB headroom = {need:.0f} MB) of {args.limit} MB")
    if need > args.limit:
        print("TOO BIG: will not fit. See README, 'Cloud deploy'.")
        return 1
    print("OK: fits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
