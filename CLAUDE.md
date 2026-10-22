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
- Days 1-3 done and verified: full crawl (434 pages, 6,243 chunks), Voyage AI index, hybrid
  retrieval + rerank + grounded LLM answers, FastAPI chat server with conversation memory -
  all live-tested against the real site and real API calls.
- Day 4 in progress: `eval/questions.json` (30 real questions) + `scripts/run_eval.py`. Running
  it un-paced gives misleadingly bad numbers (a provider capacity limit, not answer quality) -
  see `docs/SPEC.md` deviations log before trusting a fast automated run; a human-paced spot
  check (~20s between questions) is the reliable signal.
- Open PR not yet merged: `fix/openrouter-model-default` - brings in fixes that were pushed
  after the branches carrying them were already merged (working OpenRouter model default,
  NetFree/Voyage notes, SPEC deviations log, and a prompt fix: cite every source actually used,
  not just one "main" URL - found via a real chat-ui answer that mixed topics under one citation).
- Ahuva is also running a SEPARATE Claude Code session in this same folder (`feature/chat-ui`
  branch) building the real visual chat design. That session's work and this one's can touch
  the same backend files (`src/fnx_bot/answer/`) - check `git log`/`git status` for what the
  other session has done before assuming a file is in the state you last saw it.
- Submission deadline: Ahuva said "today" (treat as the live constraint, not the 2026-10-28
  date in docs/SPEC.md's own header - that date was the original target before this got moved
  up). Day 4 (30-question eval, live demo) and the chat-ui design are what's left.

## Layout
- `config/crawl.json` areas (car, apartment, travel, service), URL/heading keywords, chunk size
- `scripts/crawl.py map|fetch|process|all` -> `data/urls.txt`, `data/raw/`, `data/chunks.jsonl`, `data/stats.json`
- `scripts/build_index.py [--query "..."]` -> Voyage AI embeddings -> `data/chroma`
- `scripts/hebrew_check.py` embedding sanity check
- `data/` is git-ignored output

## Commands
- Install: `pip install -r requirements.txt`
- Tests (offline, no keys): `python -m pytest -q`
- Day 1: `python scripts/crawl.py all` then `python scripts/build_index.py`

## Saving tokens
- Don't read `data/` files whole; use `head`, `data/stats.json`, or a short script that prints a summary.
- Don't re-read `docs/SPEC.md` every task; read the relevant section.
