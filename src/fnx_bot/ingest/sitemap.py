"""Step 1: map the site from robots.txt + sitemaps, and filter URLs."""
from __future__ import annotations

import gzip
import urllib.robotparser
from collections import Counter
from urllib.parse import unquote, urldefrag, urlparse

import requests
from bs4 import BeautifulSoup

from ..config import CrawlConfig


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query = f"?{p.query}" if p.query else ""
    return f"{p.scheme.lower()}://{p.netloc.lower()}{path}{query}"


def is_pdf(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def url_allowed(url: str, cfg: CrawlConfig) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or p.netloc.lower() not in cfg.allowed_hosts:
        return False
    full = unquote(url).lower()
    if any(x.lower() in full for x in cfg.exclude_patterns):
        return False
    if is_pdf(url) and not cfg.include_pdfs:
        return False
    return True


def area_for_url(url: str, cfg: CrawlConfig) -> str | None:
    """The spec area (car, apartment, travel, service) a URL belongs to, by keywords in its path."""
    p = urlparse(url)
    path = unquote(p.path + ("?" + p.query if p.query else "")).lower()
    for key, area in cfg.areas.items():
        if any(k.lower() in path for k in area.get("url_keywords", [])):
            return key
    return None


def area_for_page(url: str, title: str, markdown: str, cfg: CrawlConfig) -> str | None:
    """Area by URL first; otherwise by keywords in the page title and headings."""
    by_url = area_for_url(url, cfg)
    if by_url:
        return by_url
    heads = " ".join([title] + [ln for ln in markdown.splitlines() if ln.startswith("#")])
    best, best_n = None, 0
    for key, area in cfg.areas.items():
        n = sum(heads.count(k) for k in area.get("text_keywords", []))
        if n > best_n:
            best, best_n = key, n
    return best


def parse_sitemap(xml: bytes) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemap_urls) from a sitemap or sitemap index."""
    if xml[:2] == b"\x1f\x8b":
        xml = gzip.decompress(xml)
    soup = BeautifulSoup(xml, "xml")
    children = [loc.get_text(strip=True) for sm in soup.find_all("sitemap") if (loc := sm.find("loc"))]
    pages = [loc.get_text(strip=True) for u in soup.find_all("url") if (loc := u.find("loc"))]
    return pages, children


class SiteMapper:
    def __init__(self, cfg: CrawlConfig, session: requests.Session | None = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = cfg.user_agent
        self.robots = urllib.robotparser.RobotFileParser()
        self.robots_sitemaps: list[str] = []

    def load_robots(self) -> None:
        url = self.cfg.base_url.rstrip("/") + "/robots.txt"
        try:
            r = self.session.get(url, timeout=20)
            lines = r.text.splitlines() if r.ok else []
            if r.status_code in (401, 403):
                lines = ["User-agent: *", "Disallow: /"]  # same rule as urllib.robotparser.read()
        except requests.RequestException:
            lines = []
        self.robots.parse(lines)
        self.robots_sitemaps = [
            ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("sitemap:")
        ]
        delay = self.robots.crawl_delay(self.cfg.user_agent)
        if delay and float(delay) > self.cfg.delay_seconds:
            self.cfg.delay_seconds = float(delay)

    def can_fetch(self, url: str) -> bool:
        return self.robots.can_fetch(self.cfg.user_agent, url)

    def discover(self) -> list[str]:
        self.load_robots()
        queue = list(dict.fromkeys(self.robots_sitemaps + self.cfg.sitemaps))
        seen_maps: set[str] = set()
        urls: list[str] = []
        while queue:
            sm = queue.pop(0)
            if sm in seen_maps:
                continue
            seen_maps.add(sm)
            try:
                r = self.session.get(sm, timeout=30)
                if not r.ok:
                    continue
            except requests.RequestException:
                continue
            pages, children = parse_sitemap(r.content)
            urls.extend(pages)
            queue.extend(children)
        urls.extend(self.cfg.seed_urls)
        return self.filter(urls)

    def filter(self, urls: list[str]) -> list[str]:
        """Allowed, robots-permitted, de-duplicated URLs (any area)."""
        out: list[str] = []
        seen: set[str] = set()
        for u in urls:
            n = normalize_url(u)
            if n in seen or not url_allowed(n, self.cfg) or not self.can_fetch(n):
                continue
            seen.add(n)
            out.append(n)
        return out


def split_by_scope(urls: list[str], cfg: CrawlConfig) -> tuple[list[str], list[str]]:
    """(in_scope, out_of_scope). Seed URLs always count as in scope, so links can be found from them."""
    seeds = {normalize_url(u) for u in cfg.seed_urls}
    ins, outs = [], []
    for u in urls:
        (ins if u in seeds or area_for_url(u, cfg) else outs).append(u)
    return ins, outs


def section_counts(urls: list[str]) -> Counter:
    """How many URLs per first path segment; shown after `map` to tune area keywords."""
    c: Counter = Counter()
    for u in urls:
        seg = unquote(urlparse(u).path).strip("/").split("/")[0] or "(home)"
        c[seg] += 1
    return c
