"""Step 3: drop boilerplate that repeats across many pages (menus, footers, cookie notes)."""
from __future__ import annotations

import re
from collections import Counter

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BLANKS = re.compile(r"\n{3,}")


def _key(line: str) -> str:
    return " ".join(line.split())


def normalize_markdown(md: str) -> str:
    md = _MD_IMAGE.sub("", md)
    # Keep link text, drop the target: sources are tracked per page, not per inline link.
    md = _MD_LINK.sub(r"\1", md)
    lines = [ln.rstrip() for ln in md.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def find_boilerplate(pages: list[str], min_share: float = 0.5, min_pages: int = 3) -> set[str]:
    """Lines that appear on at least `min_share` of pages are boilerplate."""
    if len(pages) < min_pages:
        return set()
    counts: Counter = Counter()
    for md in pages:
        counts.update({_key(ln) for ln in md.splitlines() if _key(ln)})
    threshold = max(min_pages, int(len(pages) * min_share))
    # Headings are kept even when common ("שאלות נפוצות" can be a real section title).
    return {ln for ln, n in counts.items() if n >= threshold and not ln.startswith("#")}


def strip_boilerplate(md: str, boilerplate: set[str]) -> str:
    kept = [ln for ln in md.splitlines() if _key(ln) not in boilerplate]
    return _BLANKS.sub("\n\n", "\n".join(kept)).strip()


_HEBREW = re.compile(r"[֐-׿]")


def hebrew_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _HEBREW.match(c)) / len(letters)
