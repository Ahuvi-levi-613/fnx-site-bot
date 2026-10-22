#!/usr/bin/env python3
"""Day-two terminal check: ask a question, get an answer with source links.

  python scripts/ask.py "איך מגישים תביעה על נזקי מים?"
  python scripts/ask.py "..." --area apartment

Needs VOYAGE_API_KEY, COHERE_API_KEY, and at least one of GEMINI_API_KEY/GROQ_API_KEY/
OPENROUTER_API_KEY in .env, plus a built index (python scripts/build_index.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Hebrew output on a Windows console that isn't UTF-8 would otherwise crash.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

from fnx_bot.answer.llm import LLMClient  # noqa: E402
from fnx_bot.answer.pipeline import AnswerPipeline  # noqa: E402
from fnx_bot.answer.rerank import CohereReranker  # noqa: E402
from fnx_bot.answer.retrieve import HybridRetriever  # noqa: E402
from fnx_bot.config import DATA_DIR, ROOT  # noqa: E402
from fnx_bot.index.embed import VoyageEmbedder  # noqa: E402
from fnx_bot.index.store import ChromaStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--area", help="car, apartment, travel, or service")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    embedder = VoyageEmbedder(cache_path=DATA_DIR / "embeddings_cache.jsonl")
    pipeline = AnswerPipeline(
        retriever=HybridRetriever(embedder, ChromaStore()),
        reranker=CohereReranker(),
        llm=LLMClient(),
    )
    result = pipeline.answer(args.question, area=args.area)
    print(result.text)
    if result.sources:
        print("\nמקורות:")
        for s in result.sources:
            print(f"  {s.page_title} — {s.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
