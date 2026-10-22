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
- Day 1 done and verified: full crawl (434 pages, 6,243 chunks), embedded with Voyage AI (see `docs/SPEC.md` deviations log), indexed in Chroma, sanity-checked with a real semantic query.
- Day 2 done and verified: hybrid retrieval + Cohere rerank + grounded LLM answers, live-tested against the real site and real API calls.
- Day 3 done and verified: FastAPI chat server with conversation memory, temporary test page, live-tested end to end.
- Three branches, not yet merged: `feature/voyage-embeddings`, `feature/answer-layer`, `feature/chat-server` (merge in that order - `chat-server` depends on both).
- Next: real chat UI design (see the "פני" design artifact), then day 4 (30-question test set).

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
