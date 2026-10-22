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
| travel | info for customers, what to do abroad, FAQ |
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

## Challenge rules (from the Phoenix challenge guidelines; must always hold)
- **Single source:** only content on the Phoenix site. No outside knowledge, no guesses.
- **Citation:** every answer includes the URL of the page it came from. No source -> no answer, give a referral.
- **Limits:** no personal advice, no access to customer data. Explain what the site says.
- **Hebrew:** clear, concise answers, with room for a follow-up question.
- Measure "not answering" too: correct refusals are half the score in the real world.
- Polite crawl rate, public areas only. Save the crawl date so content can be refreshed.

Reference dialog from the guidelines:
- "I have a leak at home, how do I file a claim?" -> finds "water damage claim - apartment insurance" page,
  answers in ~3 sentences (what to prepare, where to file, what happens next), ends with the fnx.co.il source.
- "And how long until I get an answer?" -> answers from the same page, or says it isn't written and refers to customer service.
- "Does my policy cover this?" -> "I can explain what the coverage includes per the site, but your personal policy
  is checked by customer service."

## Hackathon submission (from the challenge guidelines)
Working chat; live demo of 20-30 questions; source code + run instructions; short summary: how content was collected,
how the passage is chosen, limits, and how content is refreshed.

## Deviations from this spec (log)

Dated, with the reason, so later decisions have the context behind them.

- **2026-10-22 - Embeddings: Voyage AI instead of Gemini Embedding 2.** Changed because Gemini
  Embedding 2's free tier caps at 1,000 requests/day, which can't embed a 6,243-chunk index in
  reasonable time. Voyage AI (already the documented backup) is the one actually used;
  `GeminiEmbedder` stays in the code and tested, in case the primary becomes usable again.
- **2026-10-22 - Voyage AI needs a payment method on file to run at a usable speed.** Changed
  because without one, Voyage throttles to 3 requests/min and 10K tokens/min (the free
  200M-token allowance still applies either way - a card only removes the throttle, it does not
  spend money within that allowance).
- **2026-10-22 - Groq is not actually usable as an LLM fallback on this dev machine.** Changed
  because the NetFree content filter here blocks POST requests to Groq's `chat/completions`
  endpoint specifically (GET requests, e.g. listing models, go through fine). OpenRouter is
  unaffected. The code still tries Gemini -> Groq -> OpenRouter in that order (harmless to try
  Groq and fall through), but in practice OpenRouter carries the real backup role on this
  machine - worth knowing before assuming the fallback chain works end to end from a demo on
  the same network.
- **2026-10-22 - OpenRouter default model changed to `recursive/flint-v1.0:free`.** Changed
  because the previously assumed free model (`meta-llama/llama-3.3-70b-instruct:free`) stopped
  being offered for free. Verified the replacement with a real Hebrew prompt. OpenRouter's free
  lineup shifts over time, so this is a one-line env var (`OPENROUTER_MODEL`) if it happens again.
- **2026-10-22 - Cohere's trial rerank key caps at 10 requests/min.** Found while running the
  Day 4 eval suite un-paced: 30+ back-to-back pipeline calls hit the limit almost immediately,
  producing answers that looked like quality failures but were actually rate-limit noise.
  `scripts/run_eval.py` paces calls and retries a transient failure before counting it; a live
  demo (one question at a time, human-paced) isn't affected.
