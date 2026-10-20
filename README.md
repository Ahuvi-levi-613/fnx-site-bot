# בוט לאתר הפניקס (fnx-site-bot)

בוט שיחה בעברית שעונה על שאלות **רק** מתוך האתר הציבורי של הפניקס (fnx.co.il), וכל תשובה מצרפת קישור לעמוד המקור.
כשהמידע לא מופיע באתר, הבוט אומר זאת במפורש ומציג את דרכי הקשר מעמוד "צור קשר".

פרויקט לאתגר הפניקס בהאקתון "קוד פתוח 2026". ערב הגמר: 28.10.2026. האפיון המלא נמצא במסמך האפיון של הפרויקט.

## היקף הגרסה הראשונה

ביטוח רכב, ביטוח דירה, ביטוח נסיעות לחו"ל ושירות לקוחות, מתוך עמודי אינטרנט בלבד. קבצי PDF יתווספו בשדרוג עתידי.

## ארכיטקטורה

```
איסוף:   fnx.co.il ─► מיפוי (robots + sitemap, סינון לפי תחום) ─► Firecrawl / גיבוי ישיר ─► ניקוי ─► חיתוך ─► data/chunks.jsonl
אינדקס:  chunks ─► Gemini Embedding 2 ─► Chroma מקומי (data/chroma)
מענה:    שאלה ─► אחזור היברידי ─► Cohere Rerank ─► Gemini Flash (גיבוי: Groq, OpenRouter) ─► FastAPI ─► דף צ'אט מימין לשמאל
```

כלל הברזל: אין מקור, אין תשובה.

## סטטוס

| יום | מה | מצב |
| --- | --- | --- |
| 1 | הקמה, סריקת התחומים, ניקוי, חיתוך, אינדקס ב-Chroma | ✅ קוד מוכן, ממתין להרצה על האתר |
| 2 | שכבת התשובה: אחזור היברידי, דירוג מחדש, פרומפט מחייב, בדיקת מקור, מעבר לגיבוי | ⏳ |
| 3 | שרת FastAPI, דף צ'אט מעוצב, כרטיסי מקור, זיכרון שיחה | ⏳ |
| 4 | 30 שאלות בדיקה + 5 שיחות המשך, שיפורים והגשה | ⏳ |

## התקנה (PyCharm)

```bash
python -m venv .venv && source .venv/bin/activate      # ב-Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # ולמלא מפתחות. הקובץ .env לא נכנס ל-git.
```

## יום 1: איסוף ואינדקס

```bash
python scripts/hebrew_check.py     # בדיקה שמודל ההטמעה מבין עברית (דורש GEMINI_API_KEY)
python scripts/crawl.py map        # מיפוי: כמה עמודים נמצאו בכל תחום
python scripts/crawl.py fetch      # סריקה מנומסת (ממשיכה מאיפה שעצרה; מטמון ב-data/raw/)
python scripts/crawl.py process    # ניקוי וחיתוך -> data/chunks.jsonl, סיכום ב-data/stats.json
python scripts/build_index.py      # הטמעות ובניית האינדקס ב-data/chroma

# בדיקה מהירה של האינדקס:
python scripts/build_index.py --query "איך מגישים תביעה על נזקי מים?"
```

### איך נקבע מה נכנס

לכל תחום ב-[`config/crawl.json`](config/crawl.json) יש:
- `url_keywords`: מילים בכתובת העמוד (למשל car, travel). לפיהן נבחרים עמודים במיפוי ונעקבים קישורים בסריקה.
- `text_keywords`: מילים בכותרות העמוד (למשל "ביטוח דירה"). לעמוד שהכתובת שלו לא אומרת כלום, התחום נקבע לפי הכותרות.

`map` מראה כמה עמודים נמצאו בכל תחום, ומה נשאר בחוץ לפי חלקי האתר. אם תחום יוצא 0, מוסיפים לו מילת כתובת מתוך הרשימה שבחוץ ומריצים שוב.
אם כתובות האתר לא כוללות מילים מזהות בכלל, אפשר להריץ `fetch --any-area`: כל קישור באתר ייסרק (עד `CRAWL_MAX_PAGES`), ו-`process` ישאיר רק עמודים מהתחומים.

### מה יוצא

כל שורה ב-`data/chunks.jsonl` היא קטע אחד:

```json
{"id": "…", "url": "https://www.fnx.co.il/…", "page_title": "…", "heading_path": ["ביטוח דירה", "נזקי מים"],
 "text": "…", "chunk_index": 0, "crawled_at": "2026-10-21T08:00:00+00:00", "area": "apartment"}
```

- החיתוך הוא לפי כותרות העמוד, כך שכל קטע יודע לאיזה סעיף הוא שייך. תשובה קצרה בשאלות נפוצות מצורפת לקטע הבא יחד עם השאלה שלה.
- שורות שחוזרות ברוב העמודים (תפריטים, כותרת תחתונה, באנרים) מוסרות אוטומטית.
- ב-Chroma כל קטע נשמר עם הכתובת, הכותרת, התחום ותאריך האיסוף, כדי שכל תשובה תוכל לצטט מקור.
- ההטמעות נשמרות במטמון (`data/embeddings_cache.jsonl`), כך שבנייה חוזרת לא מבזבזת מכסה על קטעים שלא השתנו.

## בדיקות

```bash
python -m pytest -q
```

הבדיקות רצות בלי רשת ובלי מפתחות, על קבצי דוגמה ב-`tests/fixtures/`.

## מפתחות

| משתנה | מתי | איפה מקבלים |
| --- | --- | --- |
| `GEMINI_API_KEY` | יום 1 (הטמעות), יום 2 (מודל שפה) | aistudio.google.com |
| `FIRECRAWL_API_KEY` | יום 1, לא חובה | firecrawl.dev |
| `COHERE_API_KEY` | יום 2 | dashboard.cohere.com (מפתח ניסיון) |
| `GROQ_API_KEY`, `OPENROUTER_API_KEY` | יום 2, גיבוי | console.groq.com, openrouter.ai |

מפתחות נשמרים רק ב-`.env`, לא בקוד ולא ב-git.

## מבנה

```
config/crawl.json          תחומים, סינון וחיתוך
scripts/crawl.py           איסוף: map | fetch | process | all
scripts/build_index.py     בניית האינדקס ב-Chroma, ובדיקת חיפוש
scripts/hebrew_check.py    בדיקת עברית למודל ההטמעה
src/fnx_bot/ingest/        sitemap.py · fetch.py · clean.py · chunk.py · pipeline.py
src/fnx_bot/index/         embed.py (Gemini) · store.py (Chroma)
tests/                     בדיקות + קבצי דוגמה
data/                      פלט (לא נכנס ל-git)
```
