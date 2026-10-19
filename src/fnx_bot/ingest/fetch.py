"""Step 2: fetch each page as clean Markdown (Firecrawl, or a built-in fallback)."""
from __future__ import annotations

import io
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from ..config import CrawlConfig
from .sitemap import is_pdf

# Page parts that are never content.
STRIP_TAGS = ["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "svg", "iframe"]
STRIP_ROLES = ["navigation", "banner", "contentinfo", "search"]
BLOCK_TAGS = [
    "address", "article", "blockquote", "details", "dialog", "dd", "div", "dl", "dt", "fieldset",
    "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "main", "ol", "p", "pre", "section",
    "summary", "table", "ul",
]


@dataclass
class Page:
    url: str
    title: str
    markdown: str
    fetched_with: str
    links: list[str]


class FetchError(Exception):
    pass


def _with_retry(fn, tries: int = 4):
    """Retry on 429 / 5xx with growing waits (2, 4, 8 s)."""
    for i in range(tries):
        try:
            r = fn()
        except requests.RequestException as e:
            if i == tries - 1:
                raise FetchError(str(e)) from e
        else:
            if r.status_code != 429 and r.status_code < 500:
                return r
            if i == tries - 1:
                return r
        time.sleep(2 ** (i + 1))
    raise FetchError("unreachable")


# ---------- HTML -> Markdown (fallback, no API key needed) ----------

def _inline(node) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    return "".join(_inline(c) for c in node.children)


def _block_md(el: Tag, out: list[str]) -> None:
    name = el.name
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        text = " ".join(_inline(el).split())
        if text:
            out.append("#" * int(name[1]) + " " + text)
        return
    if name == "p":
        text = " ".join(_inline(el).split())
        if text:
            out.append(text)
        return
    if name in ("ul", "ol"):
        for i, li in enumerate(el.find_all("li", recursive=False), 1):
            text = " ".join(_inline(li).split())
            if text:
                out.append(f"{i}. {text}" if name == "ol" else f"- {text}")
        return
    if name == "table":
        for tr in el.find_all("tr"):
            cells = [" ".join(_inline(td).split()) for td in tr.find_all(["td", "th"])]
            if any(cells):
                out.append("| " + " | ".join(cells) + " |")
        return
    if name in ("dt", "summary") and el.find_parent(["details", "dl"]) is not None:
        # FAQ accordions: question text
        text = " ".join(_inline(el).split())
        if text:
            out.append("### " + text)
        return
    if el.find(BLOCK_TAGS) is None:
        # Only inline content inside: keep it as one paragraph, in order.
        text = " ".join(_inline(el).split())
        if text:
            out.append(text)
        return
    # Mixed container: walk children in order, gathering loose inline runs.
    run: list[str] = []

    def flush() -> None:
        text = " ".join("".join(run).split())
        if text:
            out.append(text)
        run.clear()

    for c in el.children:
        if isinstance(c, Tag) and (c.name in BLOCK_TAGS or c.find(BLOCK_TAGS) is not None):
            flush()
            _block_md(c, out)
        else:
            run.append(_inline(c))
    flush()


def html_to_markdown(html: str, base_url: str) -> tuple[str, str, list[str]]:
    """Return (title, markdown, absolute_links)."""
    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.split())
    links = [urljoin(base_url, a["href"]) for a in soup.find_all("a", href=True)]
    for t in soup(STRIP_TAGS):
        t.decompose()
    for role in STRIP_ROLES:
        for t in soup.find_all(attrs={"role": role}):
            t.decompose()
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    out: list[str] = []
    _block_md(root, out)
    if not title:
        h1 = soup.find("h1")
        title = " ".join(h1.get_text().split()) if h1 else ""
    return title, "\n\n".join(out), links


def pdf_to_markdown(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, p in enumerate(reader.pages, 1):
        text = (p.extract_text() or "").strip()
        if text:
            pages.append(f"## עמוד {i}\n\n{text}")
    return "\n\n".join(pages)


# ---------- Fetchers ----------

class Fetcher:
    def __init__(self, cfg: CrawlConfig, session: requests.Session | None = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = cfg.user_agent

    def fetch(self, url: str) -> Page:
        if is_pdf(url):
            return self._fetch_pdf(url)
        if self.cfg.firecrawl_api_key:
            try:
                return self._fetch_firecrawl(url)
            except FetchError:
                pass  # fall through to direct fetch
        return self._fetch_direct(url)

    def _fetch_direct(self, url: str) -> Page:
        r = _with_retry(lambda: self.session.get(url, timeout=30))
        if not r.ok:
            raise FetchError(f"HTTP {r.status_code}")
        r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
        title, md, links = html_to_markdown(r.text, url)
        return Page(url, title, md, "direct", links)

    def _fetch_pdf(self, url: str) -> Page:
        r = _with_retry(lambda: self.session.get(url, timeout=60))
        if not r.ok:
            raise FetchError(f"HTTP {r.status_code}")
        name = url.rsplit("/", 1)[-1]
        return Page(url, name, pdf_to_markdown(r.content), "pdf", [])

    def _fetch_firecrawl(self, url: str) -> Page:
        r = _with_retry(
            lambda: requests.post(
                f"{self.cfg.firecrawl_api_url}/scrape",
                headers={"Authorization": f"Bearer {self.cfg.firecrawl_api_key}"},
                json={"url": url, "formats": ["markdown", "links"], "onlyMainContent": True},
                timeout=90,
            )
        )
        if not r.ok:
            raise FetchError(f"Firecrawl HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        if not body.get("success"):
            raise FetchError(f"Firecrawl: {body.get('error', 'unknown error')}")
        data = body.get("data", {})
        meta = data.get("metadata", {}) or {}
        return Page(url, meta.get("title", "") or "", data.get("markdown", "") or "", "firecrawl", data.get("links", []) or [])
