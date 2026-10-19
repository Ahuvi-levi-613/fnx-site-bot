"""Run the crawl: map -> fetch -> clean -> chunk. Writes JSONL files under data/."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import DATA_DIR, CrawlConfig
from .chunk import chunk_page
from .clean import find_boilerplate, hebrew_ratio, normalize_markdown, strip_boilerplate
from .fetch import Fetcher, FetchError
from .sitemap import SiteMapper, normalize_url, section_counts, url_allowed

log = logging.getLogger("fnx_bot.crawl")


def _write_jsonl(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def run_map(cfg: CrawlConfig, data_dir: Path = DATA_DIR) -> list[str]:
    mapper = SiteMapper(cfg)
    urls = mapper.discover()
    (data_dir).mkdir(parents=True, exist_ok=True)
    (data_dir / "urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")
    log.info("Found %d URLs. By section:", len(urls))
    for seg, n in section_counts(urls).most_common(40):
        log.info("  %5d  %s", n, seg)
    return urls


def run_fetch(cfg: CrawlConfig, urls: list[str], data_dir: Path = DATA_DIR, follow_links: bool = True) -> list[dict]:
    """Fetch pages into data/raw/ (one JSON per page). Already-fetched pages are skipped, so a rerun resumes."""
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    mapper = SiteMapper(cfg)
    mapper.load_robots()
    fetcher = Fetcher(cfg)

    queue = list(dict.fromkeys(urls))
    seen = set(queue)
    pages: list[dict] = []
    failures: list[dict] = []
    while queue and len(pages) < cfg.max_pages:
        url = queue.pop(0)
        cache = raw_dir / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")
        if cache.exists():
            rec = json.loads(cache.read_text(encoding="utf-8"))
        else:
            try:
                page = fetcher.fetch(url)
            except FetchError as e:
                log.warning("FAIL %s (%s)", url, e)
                failures.append({"url": url, "error": str(e)})
                continue
            rec = {
                "url": url,
                "title": page.title,
                "markdown": page.markdown,
                "fetched_with": page.fetched_with,
                "links": page.links,
                "crawled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            cache.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            log.info("OK   %s [%s, %d chars]", url, page.fetched_with, len(page.markdown))
            time.sleep(cfg.delay_seconds)
        pages.append(rec)
        if follow_links:
            for link in rec.get("links", []):
                n = normalize_url(link)
                if n not in seen and url_allowed(n, cfg) and mapper.can_fetch(n):
                    seen.add(n)
                    queue.append(n)
    _write_jsonl(data_dir / "failures.jsonl", failures)
    return pages


def run_process(cfg: CrawlConfig, pages: list[dict], data_dir: Path = DATA_DIR) -> dict:
    """Clean and chunk fetched pages. Writes pages.jsonl and chunks.jsonl."""
    normalized = [normalize_markdown(p.get("markdown", "")) for p in pages]
    boiler = find_boilerplate(normalized)
    page_rows, chunk_rows, skipped = [], [], []
    for p, md in zip(pages, normalized):
        md = strip_boilerplate(md, boiler)
        if len(md) < 80:
            skipped.append({"url": p["url"], "reason": "too little text"})
            continue
        page_rows.append(
            {
                "url": p["url"],
                "title": p.get("title", ""),
                "crawled_at": p.get("crawled_at", ""),
                "fetched_with": p.get("fetched_with", ""),
                "chars": len(md),
                "hebrew_ratio": round(hebrew_ratio(md), 3),
                "markdown": md,
            }
        )
        for c in chunk_page(
            p["url"], p.get("title", ""), md, p.get("crawled_at", ""), cfg.chunk_max_chars, cfg.chunk_overlap_chars
        ):
            chunk_rows.append(c.to_dict())
    stats = {
        "pages_fetched": len(pages),
        "pages_kept": _write_jsonl(data_dir / "pages.jsonl", page_rows),
        "chunks": _write_jsonl(data_dir / "chunks.jsonl", chunk_rows),
        "boilerplate_lines_removed": len(boiler),
        "pages_skipped": len(skipped),
        "low_hebrew_pages": sum(1 for r in page_rows if r["hebrew_ratio"] < 0.5),
    }
    _write_jsonl(data_dir / "skipped.jsonl", skipped)
    (data_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def load_cached_pages(data_dir: Path = DATA_DIR) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((data_dir / "raw").glob("*.json"))]
