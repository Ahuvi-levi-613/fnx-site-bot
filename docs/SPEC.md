# Spec summary (approved 2026-10-20)

Source of truth: the Hebrew spec "מסמך אפיון: בוט לאתר הפניקס" (approved by Ahuva). This file is its English summary.

## Goal
Hebrew chat bot that answers questions **only** from the public site fnx.co.il. Every answer links to its source page(s).
When the site has no answer, it says so explicitly and never invents. Built by one person for the "קוד פתוח 2026"
hackathon (Phoenix challenge). Final: Wed 2026-10-28.
Users: anyone visiting the site. No personal advice, no access to customer data.

## Scope v1
In: web pages only, four areas:
| Area | Includes |
| --- | --- |
| car | products, car property + compulsory claims, FAQ |
| apartment | products, home damage claims, FAQ |
| travel | info for customers, what to do abroad |
| service | contact options, common actions, FAQ |
Out: PDFs (forms, booklets, policy terms) — future upgrade; other site areas; login-only areas; personal data.

## Functional requirements
1. Free Hebrew question -> clear Hebrew answer.
2. Length fits the question: short for simple; steps for processes (what to prepare, where to file, what happens next).
3. Every answer cites the page URL(s) it came from. No source, no answer.
4. Not on the site: say so explicitly, don't guess, show contact options from the site's contact page
   (phone, WhatsApp, email) with a link.
5. Conversation memory: follow-ups like "and how long does it take?" are understood.
6. Personal policy / advice questions: general explanation from the site + referral to customer service.
7. Unclear question: short clarifying question (e.g. "car or apartment?").
Fixed rules: single source (site only, no outside knowledge); natural, pleasant Hebrew; privacy (never ask for or store personal details).

## Architecture (all free tier, Python)
| Part | Tool | Backup |
| --- | --- | --- |
| Crawl | Firecrawl (1,000 pages/month) | Crawl4AI / built-in fetcher |
| Embeddings | Gemini Embedding 2 | Voyage AI |
| Vector DB | Chroma, local file, no account | Supabase pgvector |
| Rerank | Cohere Rerank (trial key) | none |
| LLM | Gemini Flash | on 429: wait, then Groq, then OpenRouter (user shouldn't notice) |
| Server | FastAPI | — |
| UI | custom RTL chat page: bubbles, source cards, subtle animation (not Streamlit) | Streamlit |
Retrieval is hybrid: semantic + keyword. Keys only in `.env`, never in code or git.

## Testing
30 questions written after the crawl from real pages of the four areas: 20 answerable, 10 not, plus 5 short follow-up
dialogs and a few personal-policy questions. Each has: question, expected answer + URL (or "not on site").
One script runs all of them after every change.
| Metric | Target |
| --- | --- |
| Accuracy (answerable) | 18/20 |
| Correct refusal + contact options | 10/10 |
| Source link points to the page with the answer | every answer |
| Inventions (detail not in source) | 0 |
| Follow-ups understood | 5/5 |

## Schedule (4 dev days, 15:30-19:00)
1. Setup + crawl: keys, PyCharm project, crawl the four areas, clean, chunk. End: full index in Chroma.
2. Answer layer: hybrid retrieval, rerank, site-only prompt, source check, automatic LLM fallback. End: answers with links in a terminal.
3. UI + memory: FastAPI, RTL chat page, source cards, history, follow-ups. End: full chat in the browser.
4. Test + submit: write the 30 questions, run, improve, run instructions + short summary. End: demo-ready.
If a day runs long, cut design first, never testing: the key metric is that the bot doesn't invent.

## Hackathon submission (from the challenge guidelines)
Working chat; live demo of 20-30 questions; source code + run instructions; short summary: how content was collected,
how the passage is chosen, limits, and how content is refreshed.
