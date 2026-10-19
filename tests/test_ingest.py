from pathlib import Path

import pytest

from fnx_bot.config import CrawlConfig
from fnx_bot.ingest import pipeline
from fnx_bot.ingest.chunk import chunk_embedding_text, chunk_page
from fnx_bot.ingest.clean import find_boilerplate, hebrew_ratio, normalize_markdown, strip_boilerplate
from fnx_bot.ingest.fetch import Page, html_to_markdown
from fnx_bot.ingest.sitemap import SiteMapper, normalize_url, parse_sitemap, url_allowed

FIX = Path(__file__).parent / "fixtures"


def cfg(**kw):
    base = dict(
        base_url="https://www.fnx.co.il",
        allowed_hosts=["www.fnx.co.il"],
        sitemaps=["https://www.fnx.co.il/sitemap.xml"],
        seed_urls=[],
        exclude_patterns=["/login"],
        delay_seconds=0,
    )
    base.update(kw)
    return CrawlConfig(**base)


class FakeResp:
    def __init__(self, status=200, text="", content=b""):
        self.status_code, self.text, self.content = status, text, content or text.encode()
        self.ok = status < 400


class FakeSession:
    def __init__(self, routes):
        self.routes, self.headers = routes, {}

    def get(self, url, timeout=None):
        return self.routes.get(url, FakeResp(404))


# ---------- sitemap ----------

def test_normalize_url():
    assert normalize_url("HTTPS://WWW.fnx.co.il/a/b/#top") == "https://www.fnx.co.il/a/b"
    assert normalize_url("https://www.fnx.co.il") == "https://www.fnx.co.il/"


def test_url_allowed():
    c = cfg()
    assert url_allowed("https://www.fnx.co.il/claims", c)
    assert not url_allowed("https://www.fnx.co.il/login", c)
    assert not url_allowed("https://evil.com/claims", c)
    assert not url_allowed("https://www.fnx.co.il/a.pdf", cfg(include_pdfs=False))
    assert not url_allowed("https://www.fnx.co.il/x", cfg(include_patterns=["claims"]))


def test_parse_sitemap_index():
    pages, children = parse_sitemap((FIX / "sitemap_index.xml").read_bytes())
    assert pages == [] and children == ["https://www.fnx.co.il/sitemap-pages.xml"]


def test_discover_follows_index_and_respects_robots():
    robots = "User-agent: *\nDisallow: /private\nSitemap: https://www.fnx.co.il/sitemap.xml\n"
    s = FakeSession(
        {
            "https://www.fnx.co.il/robots.txt": FakeResp(text=robots),
            "https://www.fnx.co.il/sitemap.xml": FakeResp(content=(FIX / "sitemap_index.xml").read_bytes()),
            "https://www.fnx.co.il/sitemap-pages.xml": FakeResp(content=(FIX / "sitemap_pages.xml").read_bytes()),
        }
    )
    urls = SiteMapper(cfg(), session=s).discover()
    assert urls == ["https://www.fnx.co.il/claims/water", "https://www.fnx.co.il/forms/a.pdf"]


# ---------- html -> markdown ----------

def test_html_to_markdown_keeps_content_drops_chrome():
    title, md, links = html_to_markdown((FIX / "page.html").read_text(encoding="utf-8"), "https://www.fnx.co.il/claims")
    assert title == "תביעת נזקי מים | דוגמה"
    assert "# תביעת נזקי מים" in md
    assert "## מה צריך להכין" in md
    assert "- תמונות של הנזק" in md
    assert "### תוך כמה זמן מטפלים?" in md
    assert "מגישים תביעה על נזקי מים" in md  # inline link text stays in order
    assert "טקסט חופשי בתוך div מודגש וממשיך." in md
    assert md.index("וממשיך.") < md.index("פסקה פנימית.")
    assert "ראשי" not in md and "כל הזכויות שמורות" not in md and "var x" not in md
    assert "https://www.fnx.co.il/forms/water.pdf" in links


# ---------- cleaning ----------

def test_boilerplate_removed_but_headings_kept():
    pages = [f"## שאלות נפוצות\nקבלו הצעה עכשיו\nתוכן ייחודי {i}" for i in range(4)]
    boiler = find_boilerplate(pages)
    assert "קבלו הצעה עכשיו" in boiler
    assert "## שאלות נפוצות" not in boiler
    assert strip_boilerplate(pages[0], boiler) == "## שאלות נפוצות\nתוכן ייחודי 0"


def test_normalize_markdown_drops_images_and_link_targets():
    md = normalize_markdown("![logo](x.png)\n[לחצו כאן](https://a.b)\n\n\n\nסוף")
    assert md == "לחצו כאן\n\nסוף"


def test_hebrew_ratio():
    assert hebrew_ratio("שלום world") == pytest.approx(4 / 9)
    assert hebrew_ratio("123") == 0.0


# ---------- chunking ----------

def test_chunk_by_headings_with_path():
    md = "# ביטוח דירה\n\nמבוא קצר על ביטוח דירה ועל הכיסויים שבו לכל משפחה.\n\n## נזקי מים\n\nכאן מוסבר בפירוט איך מטפלים בנזקי מים שנגרמו בדירה."
    chunks = chunk_page("https://www.fnx.co.il/home", "ביטוח דירה", md, "2026-10-19")
    assert [c.heading_path for c in chunks] == [["ביטוח דירה"], ["ביטוח דירה", "נזקי מים"]]
    assert all(c.url == "https://www.fnx.co.il/home" for c in chunks)
    assert chunk_embedding_text(chunks[1]).startswith("ביטוח דירה > ביטוח דירה > נזקי מים")


def test_tiny_faq_answer_keeps_its_question():
    md = "## שאלות\n\n### תוך כמה זמן?\n\nכמה ימים.\n\n### איפה מגישים?\n\nבאתר, בעמוד התביעות, או בטלפון למוקד השירות."
    chunks = chunk_page("u", "t", md, "d")
    assert len(chunks) == 1
    assert "תוך כמה זמן?: כמה ימים." in chunks[0].text


def test_long_section_split_with_overlap():
    para = "משפט ארוך על ביטוח. " * 40  # ~800 chars
    md = "## כותרת\n\n" + para + "\n\n" + para
    chunks = chunk_page("u", "t", md, "d", max_chars=600, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c.text) <= 600 + 60 for c in chunks)
    assert chunks[1].text.startswith("…")
    assert len({c.id for c in chunks}) == len(chunks)


# ---------- pipeline (offline) ----------

def test_pipeline_fetch_and_process(tmp_path, monkeypatch):
    html = (FIX / "page.html").read_text(encoding="utf-8")

    class FakeFetcher:
        def __init__(self, c):
            pass

        def fetch(self, url):
            title, md, links = html_to_markdown(html, url)
            md += f"\n\nתוכן ייחודי לעמוד {url}: " + "פרטים על הכיסוי והתנאים. " * 5
            return Page(url, title, md, "direct", links)

    monkeypatch.setattr(pipeline, "Fetcher", FakeFetcher)
    monkeypatch.setattr(pipeline.SiteMapper, "load_robots", lambda self: self.robots.parse([]))
    c = cfg(exclude_patterns=[".pdf"], max_pages=5)
    pages = pipeline.run_fetch(c, ["https://www.fnx.co.il/claims"], data_dir=tmp_path)
    # Follows internal links (menu links too), skips the PDF and the external link
    assert [p["url"] for p in pages] == [
        "https://www.fnx.co.il/claims",
        "https://www.fnx.co.il/",
        "https://www.fnx.co.il/claims/water",
    ]
    assert len(list((tmp_path / "raw").glob("*.json"))) == 3

    stats = pipeline.run_process(c, pipeline.load_cached_pages(tmp_path), data_dir=tmp_path)
    assert stats["pages_kept"] == 3 and stats["chunks"] > 0
    rows = pipeline._read_jsonl(tmp_path / "chunks.jsonl")
    assert all(r["url"].startswith("https://www.fnx.co.il/") for r in rows)
    assert all(r["text"] for r in rows)
    # Text shared by every page is treated as boilerplate and removed
    assert not any("מה צריך להכין" in r["text"] and "תמונות של הנזק" in r["text"] for r in rows)
