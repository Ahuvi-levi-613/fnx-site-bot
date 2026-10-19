# בוט לאתר הפניקס (fnx-site-bot)

בוט שיחה בעברית שעונה על שאלות **רק** מתוך האתר הציבורי של הפניקס (fnx.co.il), וכל תשובה מצרפת קישור לעמוד המקור.
כשהמידע לא מופיע באתר, הבוט אומר "זה לא כתוב באתר" ומפנה לשירות הלקוחות.

פרויקט לאתגר הפניקס בהאקתון "קוד פתוח 2026". ערב הגמר: 28.10.2026.

## ארכיטקטורה

```
איסוף:  fnx.co.il ──► מיפוי (robots + sitemap) ──► Firecrawl / גיבוי ישיר ──► ניקוי ──► חיתוך לקטעים ──► data/chunks.jsonl
אינדוקס: chunks ──► Gemini Embeddings ──► Supabase pgvector                                   (שלב הבא)
מענה:   שאלה ──► אחזור היברידי ──► Cohere Rerank ──► Gemini Flash עם מקורות ──► Streamlit      (שלב הבא)
```

כלל הברזל: אין מקור, אין תשובה.

## סטטוס

| שלב | מה | מצב |
| --- | --- | --- |
| 1 | שלד הפרויקט, מיפוי האתר, סריקה, ניקוי וחיתוך, בדיקת עברית | ✅ בקוד הזה |
| 2 | הטמעות וטעינה ל-Supabase pgvector | ⏳ |
| 3 | אחזור היברידי, דירוג מחדש, פרומפט מחייב ובדיקת מקור | ⏳ |
| 4 | ממשק צ'אט ב-Streamlit עם היסטוריה | ⏳ |
| 5 | סט בדיקה: 20 שאלות עם תשובה + 10 בלי | ⏳ |

## התקנה

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # ולמלא מפתחות. הקובץ .env לא נכנס ל-git.
```

## הרצת האיסוף (שלב 1)

```bash
python scripts/crawl.py map        # מיפוי: robots.txt + sitemap -> data/urls.txt, עם ספירה לפי אזור באתר
python scripts/crawl.py fetch      # סריקה מנומסת (ממשיכה מאיפה שעצרה; מטמון ב-data/raw/)
python scripts/crawl.py process    # ניקוי וחיתוך -> data/pages.jsonl, data/chunks.jsonl, data/stats.json
python scripts/crawl.py all        # הכל ברצף

# בדיקה על עמוד אחד:
python scripts/crawl.py fetch --url https://www.fnx.co.il/ && python scripts/crawl.py process
```

- **עם `FIRECRAWL_API_KEY`**: כל עמוד נסרק דרך Firecrawl ל-Markdown נקי (1,000 עמודים בחודש חינם).
- **בלי מפתח**: נעשה שימוש במחלץ מובנה (requests + BeautifulSoup). עובד טוב לעמודים שלא נטענים ב-JavaScript.
- קבצי PDF ציבוריים מחולצים עם pypdf.
- הסריקה מכבדת את robots.txt, ממתינה `CRAWL_DELAY_SECONDS` בין בקשות, ועוצרת אחרי `CRAWL_MAX_PAGES`.

### כיוון הסריקה

ההגדרות ב-[`config/crawl.json`](config/crawl.json):

- `include_patterns`: ריק = כל האתר. אחרי `map`, לבחור מהספירה לפי אזור את החלקים החשובים (מוצרים, תביעות, שאלות נפוצות, טפסים) ולהכניס אותם כאן.
- `exclude_patterns`: אזור אישי, התחברות, שפות אחרות, תמונות וכו'.
- `chunk_max_chars` / `chunk_overlap_chars`: גודל קטע וחפיפה.

### מה יוצא

כל שורה ב-`data/chunks.jsonl` היא קטע אחד:

```json
{"id": "…", "url": "https://www.fnx.co.il/…", "page_title": "…", "heading_path": ["ביטוח דירה", "נזקי מים"],
 "text": "…", "chunk_index": 0, "crawled_at": "2026-10-21T08:00:00+00:00"}
```

החיתוך הוא לפי כותרות העמוד, כך שכל קטע יודע לאיזה סעיף הוא שייך. תשובה קצרה בשאלות נפוצות מצורפת לקטע הבא יחד עם השאלה שלה.
שורות שחוזרות ברוב העמודים (תפריטים, כותרת תחתונה, באנרים) מוסרות אוטומטית. `stats.json` מסכם כמה עמודים נשמרו, וכמה מהם עם מעט עברית (סימן לבעיית חילוץ).

## בדיקת עברית

```bash
python scripts/hebrew_check.py     # דורש GEMINI_API_KEY
```

בודק שמודל ההטמעה מתאים שאלה בעברית (בניסוח יומיומי) לקטע הנכון. המודל נבחר ב-`GEMINI_EMBED_MODEL` (ברירת מחדל `gemini-embedding-001`).

## בדיקות

```bash
python -m pytest -q
```

הבדיקות רצות בלי רשת, על קבצי דוגמה ב-`tests/fixtures/`.

## מפתחות

| משתנה | לאיזה שלב | איפה מקבלים |
| --- | --- | --- |
| `FIRECRAWL_API_KEY` | 1 (לא חובה) | firecrawl.dev |
| `GEMINI_API_KEY` | 1 (בדיקת עברית), 2–3 | aistudio.google.com |
| `COHERE_API_KEY` | 3 | dashboard.cohere.com (מפתח ניסיון) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | 2 | supabase.com |
| `GROQ_API_KEY` / `OPENROUTER_API_KEY` | גיבוי | groq.com / openrouter.ai |

לעולם לא שומרים מפתחות בקוד או ב-git, רק ב-`.env`.

## מבנה

```
config/crawl.json          הגדרות סריקה וחיתוך
scripts/crawl.py           הרצת האיסוף
scripts/hebrew_check.py    בדיקת עברית למודל ההטמעה
src/fnx_bot/ingest/        sitemap.py · fetch.py · clean.py · chunk.py · pipeline.py
tests/                     בדיקות + קבצי דוגמה
data/                      פלט הסריקה (לא נכנס ל-git)
```
