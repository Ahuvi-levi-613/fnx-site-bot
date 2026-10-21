# fnx-site-bot

Hebrew RAG chat bot over the public site fnx.co.il. Full spec: `docs/SPEC.md` (read it before planning work).

## Working with Ahuva (the owner)
- Reply in Hebrew, short and simple. Code, comments, commits stay in English.
- Before EVERY step: say what you'll do and wait for her approval. Do nothing unapproved.
- Work only per `docs/SPEC.md`. Anything outside it: propose first.
- Never commit secrets. Keys live only in `.env` (template: `.env.example`).
- Git: never commit to `main`. Work on a branch, push it, open a pull request; Ahuva reviews and merges.

## Core rule
The bot answers only from crawled site content and cites the source URL. No source, no answer.
Not on the site -> say so + contact options from the site's contact page.
The challenge rules in `docs/SPEC.md` ("Challenge rules") are non-negotiable; check every answer-layer change against them.

## Network (NetFree filter on this machine)
- Call external APIs (Gemini, Cohere, Groq, OpenRouter, Firecrawl) with plain REST via `requests`, not vendor SDKs (gRPC is blocked).
- If SSL errors appear: `pip install pip-system-certs` (adds the NetFree certificate to Python).

## Status
- Day 1 code done: crawl (`src/fnx_bot/ingest/`) + Chroma index (`src/fnx_bot/index/`). Not yet run on the real site.
- Next: run day 1 here, tune `config/crawl.json` area keywords from the `map` output, then day 2 (answer layer).

## Layout
- `config/crawl.json` areas (car, apartment, travel, service), URL/heading keywords, chunk size
- `scripts/crawl.py map|fetch|process|all` -> `data/urls.txt`, `data/raw/`, `data/chunks.jsonl`, `data/stats.json`
- `scripts/build_index.py [--query "..."]` -> Gemini Embedding 2 -> `data/chroma`
- `scripts/hebrew_check.py` embedding sanity check
- `data/` is git-ignored output

## Commands
- Install: `pip install -r requirements.txt`
- Tests (offline, no keys): `python -m pytest -q`
- Day 1: `python scripts/crawl.py all` then `python scripts/build_index.py`

## Saving tokens
- Don't read `data/` files whole; use `head`, `data/stats.json`, or a short script that prints a summary.
- Don't re-read `docs/SPEC.md` every task; read the relevant section.
