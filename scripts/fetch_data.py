#!/usr/bin/env python3
"""Put the runtime data into data/ for a cloud build (used by the Dockerfile).

  DATA_URL=https://.../data-2026-10-25.zip python scripts/fetch_data.py

The zip holds chroma/ and chunks.jsonl at its top level. Without DATA_URL, nothing is
downloaded and the files must already be in data/. Fails loudly if they are missing.
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
NEEDED = ("chroma", "chunks.jsonl")


def main() -> int:
    url = os.environ.get("DATA_URL", "").strip()
    if url:
        print(f"Downloading data from {url}")
        with urllib.request.urlopen(url, timeout=300) as r:
            zipfile.ZipFile(io.BytesIO(r.read())).extractall(DATA)
    missing = [n for n in NEEDED if not (DATA / n).exists()]
    if missing:
        print(f"Missing in data/: {', '.join(missing)}. Set DATA_URL or put the files in data/.", file=sys.stderr)
        return 1
    print("Data ready:", ", ".join(sorted(p.name for p in DATA.iterdir())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
