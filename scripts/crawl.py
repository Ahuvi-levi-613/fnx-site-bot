#!/usr/bin/env python3
"""Crawl fnx.co.il into data/chunks.jsonl.

  python scripts/crawl.py map        # list in-scope URLs (car, apartment, travel, service) -> data/urls.txt
  python scripts/crawl.py fetch      # fetch pages (resumes; cached in data/raw/)
  python scripts/crawl.py process    # clean + chunk cached pages -> data/pages.jsonl, data/chunks.jsonl
  python scripts/crawl.py all        # all three
  python scripts/crawl.py fetch --url https://www.fnx.co.il/some-page   # one page, for testing
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Hebrew output on a Windows console that isn't UTF-8 would otherwise crash.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fnx_bot.config import DATA_DIR, load_config  # noqa: E402
from fnx_bot.ingest.pipeline import load_cached_pages, run_fetch, run_map, run_process  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["map", "fetch", "process", "all"])
    ap.add_argument("--url", action="append", help="fetch only these URLs (repeatable)")
    ap.add_argument("--max-pages", type=int, help="override CRAWL_MAX_PAGES")
    ap.add_argument("--no-follow", action="store_true", help="do not follow links found on pages")
    ap.add_argument(
        "--any-area",
        action="store_true",
        help="follow every site link, not only area-looking ones (pages are still filtered by area in `process`)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    if args.max_pages:
        cfg.max_pages = args.max_pages
    log = logging.getLogger("fnx_bot.crawl")
    log.info("Fetcher: %s", "Firecrawl" if cfg.firecrawl_api_key else "direct (no FIRECRAWL_API_KEY)")

    if args.step in ("map", "all") and not args.url:
        urls = run_map(cfg)
    if args.step in ("fetch", "all"):
        if args.url:
            urls = args.url
        elif args.step == "fetch":
            f = DATA_DIR / "urls.txt"
            urls = f.read_text(encoding="utf-8").split() if f.exists() else cfg.seed_urls
        run_fetch(cfg, urls, follow_links=not (args.no_follow or args.url), any_area=args.any_area)
    if args.step in ("process", "all"):
        stats = run_process(cfg, load_cached_pages())
        log.info(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
