#!/usr/bin/env python3
"""Build the Chroma index from data/chunks.jsonl with Gemini Embedding 2.

  python scripts/build_index.py                 # embed all chunks and (re)build data/chroma
  python scripts/build_index.py --query "איך מגישים תביעה על נזקי מים?"   # quick check: top 5 chunks + URLs

Needs GEMINI_API_KEY in .env. Embeddings are cached in data/embeddings_cache.jsonl,
so a rebuild only pays for chunks that changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

from fnx_bot.config import DATA_DIR, ROOT  # noqa: E402
from fnx_bot.index.embed import EmbedError, GeminiEmbedder, document_text  # noqa: E402
from fnx_bot.index.store import ChromaStore  # noqa: E402


def load_chunks(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def build(embedder: GeminiEmbedder, store: ChromaStore, chunks: list[dict]) -> int:
    texts = []
    for c in chunks:
        # The heading path gives a chunk its context ("ביטוח דירה > נזקי מים").
        head = " > ".join(c.get("heading_path", []))
        body = f"{head}\n\n{c['text']}" if head else c["text"]
        texts.append(document_text(c.get("page_title", ""), body))
    vectors = embedder.embed_many(texts)
    return store.rebuild(chunks, vectors)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", help="search the existing index instead of building it")
    ap.add_argument("--area", help="limit --query to one area: car, apartment, travel, service")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    embedder = GeminiEmbedder(cache_path=DATA_DIR / "embeddings_cache.jsonl")
    store = ChromaStore()
    try:
        if args.query:
            for i, r in enumerate(store.query(embedder.embed_query(args.query), k=args.k, area=args.area), 1):
                print(f"{i}. [{r['score']:.3f}] {r['area']} | {r['page_title']} > {r['heading_path']}")
                print(f"   {r['url']}")
                print(f"   {r['text'][:160].replace(chr(10), ' ')}…\n")
            return 0
        chunks_file = DATA_DIR / "chunks.jsonl"
        if not chunks_file.exists():
            print("data/chunks.jsonl not found. Run: python scripts/crawl.py all")
            return 1
        chunks = load_chunks(chunks_file)
        print(f"Embedding {len(chunks)} chunks with {embedder.model} ({embedder.dim} dims)…")
        n = build(embedder, store, chunks)
        print(f"Done: {n} chunks in data/chroma")
        return 0
    except EmbedError as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
