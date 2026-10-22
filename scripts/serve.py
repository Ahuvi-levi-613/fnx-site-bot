#!/usr/bin/env python3
"""Run the chat server for manual testing in a browser.

  python scripts/serve.py
  then open http://localhost:8000

Needs the same keys as scripts/ask.py (VOYAGE_API_KEY, COHERE_API_KEY, and at least one of
GEMINI_API_KEY/GROQ_API_KEY/OPENROUTER_API_KEY), plus a built index (scripts/build_index.py).
This serves Day 3's temporary test page - the real chat design comes separately.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from fnx_bot.config import ROOT  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    uvicorn.run("fnx_bot.server.app:app", host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
