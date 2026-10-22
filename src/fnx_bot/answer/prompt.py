"""Site-only prompt + the citation check that enforces SPEC's "no source, no answer"."""
from __future__ import annotations

import re

# Real contact page found in the crawl (data/pages.jsonl): lists phone/WhatsApp/email per
# department. We link to it rather than quoting a number, since the right one depends on area.
CONTACT_URL = "https://www.fnx.co.il/customer-service/contact-us"

NOT_ON_SITE_MESSAGE = (
    "לא מצאתי על כך מידע באתר הפניקס. אפשר לפנות לשירות הלקוחות ולבדוק מול נציג: " + CONTACT_URL
)

# Retrieval/rerank/LLM all succeeded or failed cleanly -> NOT_ON_SITE_MESSAGE is honest.
# This is for when the pipeline itself broke (a provider outage, etc) - a different problem,
# so it gets a different message instead of implying the site simply has no answer.
SERVICE_UNAVAILABLE_MESSAGE = (
    "מצטערת, יש כרגע תקלה זמנית בשירות. אפשר לנסות שוב בעוד רגע, או לפנות ישירות לשירות הלקוחות: "
    + CONTACT_URL
)

SYSTEM_PROMPT = """את עוזרת וירטואלית של חברת הביטוח הפניקס (fnx.co.il). עונה בעברית בלבד, בנימה נעימה וברורה.

חוקי יסוד (אסור לחרוג מהם):
1. עני אך ורק לפי הקטעים שסופקו לך למטה, מתוך אתר הפניקס. אסור להמציא פרטים ואסור להשתמש בידע כללי שלך.
2. אם התשובה לא נמצאת בקטעים שסופקו - אמרי זאת במפורש ואל תנחשי, ואל תצייני שום כתובת URL באותו מקרה.
3. בסוף תשובה שמבוססת על מקור, כתבי בשורה נפרדת **כתובת URL בודדת אחת** של העמוד העיקרי שבו נעזרת -
   בלי כותרת כמו "מקורות" ובלי רשימה. רשימת המקורות המלאה תוצג בנפרד על ידי המערכת, לא על ידך.
4. שאלה על פוליסה אישית ספציפית: הסבירי מה כתוב באתר באופן כללי, והפני לשירות הלקוחות לבדיקה פרטנית.
5. אל תבקשי ואל תשמרי פרטים אישיים מזהים של המשתמש.

אורך התשובה מתאים לשאלה: תשובה קצרה לשאלה פשוטה; שלבים מסודרים לתהליך (מה להכין, איפה להגיש, מה קורה אחר כך).
אם השאלה מעורפלת מדי כדי לדעת איזה תחום (רכב/דירה/נסיעות/שירות), שאלי שאלה קצרה להבהרה במקום לנחש.
אם מופיעה למטה היסטוריית שיחה קודמת, התייחסי אליה כדי להבין שאלות המשך (למשל "ומה עם רכב?" אחרי שיחה על דירה).
"""


def build_user_prompt(question: str, passages: list[dict], history: list[dict] | None = None) -> str:
    parts = []
    if history:
        convo = "\n".join(f"משתמש: {h['question']}\nעוזרת: {h['answer']}" for h in history)
        parts.append(f"היסטוריית השיחה עד כה:\n{convo}")
    if not passages:
        parts.append(f"שאלה נוכחית: {question}\n\nלא נמצאו קטעים רלוונטיים באתר.")
    else:
        blocks = []
        for p in passages:
            head = f" > {p['heading_path']}" if p.get("heading_path") else ""
            blocks.append(f"[מקור: {p['url']}]\nכותרת: {p.get('page_title', '')}{head}\n{p['text']}")
        sources = "\n\n---\n\n".join(blocks)
        parts.append(f"קטעים מהאתר:\n\n{sources}\n\n---\n\nשאלה נוכחית: {question}")
    return "\n\n===\n\n".join(parts)


_URL_RE = re.compile(r"https?://\S+")


def cited_urls(answer_text: str) -> list[str]:
    return [u.rstrip(".,)־") for u in _URL_RE.findall(answer_text)]


# The model follows rule #3 (always end with a URL) out of habit even when it's actually saying
# it doesn't know - so a URL being present isn't proof the answer is real. Catch that phrasing too.
_NOT_FOUND_PHRASES = (
    "לא מצאתי",
    "לא נמצא מידע",
    "לא מופיע באתר",
    "אין מידע על כך",
    "לא קיים מידע",
    "המידע לא מופיע",
    "לא נמצא על כך מידע",
)


def claims_not_found(answer_text: str) -> bool:
    return any(p in answer_text for p in _NOT_FOUND_PHRASES)


def is_grounded(answer_text: str, allowed_urls: set[str]) -> bool:
    """True only if the answer cites a URL it was actually given as a source (blocks invented
    links) and doesn't itself say the information isn't there (blocks a stray citation habit)."""
    if claims_not_found(answer_text):
        return False
    return any(u in allowed_urls for u in cited_urls(answer_text))
