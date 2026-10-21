"""Settings from .env and config/crawl.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


@dataclass
class CrawlConfig:
    base_url: str
    allowed_hosts: list[str]
    sitemaps: list[str]
    seed_urls: list[str]
    # Scope from the spec: area key -> {label, url_keywords, text_keywords}
    areas: dict[str, dict] = field(default_factory=dict)
    exclude_patterns: list[str] = field(default_factory=list)
    include_pdfs: bool = False  # spec v1: web pages only, PDFs are a later upgrade
    chunk_max_chars: int = 1200
    chunk_overlap_chars: int = 150
    # From .env
    firecrawl_api_key: str = ""
    firecrawl_api_url: str = "https://api.firecrawl.dev/v1"
    delay_seconds: float = 1.5
    max_pages: int = 300
    user_agent: str = "fnx-site-bot/0.1"


def load_config(path: Path | None = None) -> CrawlConfig:
    load_dotenv(ROOT / ".env")
    path = path or ROOT / "config" / "crawl.json"
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return CrawlConfig(
        **raw,
        firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", "").strip(),
        firecrawl_api_url=os.getenv("FIRECRAWL_API_URL", "https://api.firecrawl.dev/v1").rstrip("/"),
        delay_seconds=float(os.getenv("CRAWL_DELAY_SECONDS", "1.5")),
        max_pages=int(os.getenv("CRAWL_MAX_PAGES", "300")),
        user_agent=os.getenv("CRAWL_USER_AGENT", "fnx-site-bot/0.1"),
    )
