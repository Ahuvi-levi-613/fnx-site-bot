"""Step 4: split a page into chunks by its headings, with a small overlap."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    id: str
    url: str
    page_title: str
    heading_path: list[str]
    text: str
    chunk_index: int
    crawled_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _sections(md: str) -> list[tuple[list[str], str]]:
    """Return (heading_path, body) for each section of the page."""
    path: list[tuple[int, str]] = []
    out: list[tuple[list[str], str]] = []
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            out.append(([h for _, h in path], body))
        buf.clear()

    for line in md.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            level, text = len(m.group(1)), m.group(2).strip()
            path = [(lv, h) for lv, h in path if lv < level] + [(level, text)]
        else:
            buf.append(line)
    flush()
    return out


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    cur = ""
    for p in paras:
        # A single huge paragraph: cut it on sentence ends, else hard.
        while len(p) > max_chars:
            cut = max(p.rfind(". ", 0, max_chars), p.rfind("? ", 0, max_chars), p.rfind("\n", 0, max_chars))
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            head, p = p[:cut].strip(), p[cut:].strip()
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(head)
        if cur and len(cur) + 2 + len(p) > max_chars:
            pieces.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        pieces.append(cur)
    if overlap <= 0:
        return pieces
    # Prefix each piece with the tail of the one before it.
    out = [pieces[0]]
    for prev, piece in zip(pieces, pieces[1:]):
        tail = prev[-overlap:]
        sp = tail.find(" ")
        tail = tail[sp + 1 :] if 0 <= sp < len(tail) - 1 else tail
        out.append(f"…{tail}\n\n{piece}")
    return out


def chunk_page(
    url: str,
    page_title: str,
    markdown: str,
    crawled_at: str,
    max_chars: int = 1200,
    overlap: int = 150,
    min_chars: int = 40,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    pending: tuple[list[str], str] | None = None
    sections = _sections(markdown)
    # Merge tiny sections (e.g. a short FAQ answer) into the next one so they keep context.
    merged: list[tuple[list[str], str]] = []
    for path, body in sections:
        if pending:
            ppath, pbody = pending
            if ppath and ppath != path[: len(ppath)]:
                pbody = f"{ppath[-1]}: {pbody}"  # keep the tiny section's own heading
            body = f"{pbody}\n\n{body}"
            pending = None
        if len(body) < min_chars:
            pending = (path, body)
            continue
        merged.append((path, body))
    if pending:
        if merged:
            p, b = merged[-1]
            ppath, pbody = pending
            if ppath and ppath != p[: len(ppath)]:
                pbody = f"{ppath[-1]}: {pbody}"
            merged[-1] = (p, f"{b}\n\n{pbody}")
        else:
            merged.append(pending)

    for path, body in merged:
        for piece in _split_long(body, max_chars, overlap):
            idx = len(chunks)
            cid = hashlib.sha1(f"{url}#{idx}#{piece}".encode()).hexdigest()[:16]
            chunks.append(Chunk(cid, url, page_title, path, piece, idx, crawled_at))
    return chunks


def chunk_embedding_text(c: Chunk) -> str:
    """Text to embed later: title + heading path give the chunk its context."""
    head = " > ".join([c.page_title, *c.heading_path]) if c.page_title else " > ".join(c.heading_path)
    return f"{head}\n\n{c.text}" if head else c.text
