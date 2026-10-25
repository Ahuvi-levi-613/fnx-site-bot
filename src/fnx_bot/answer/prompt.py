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
0. השורה הראשונה בתשובה חייבת להיות בדיוק אחת משתי אלה, באנגלית, לבד בשורה:
   STATUS: FOUND - אם התשובה לשאלה הנוכחית באמת נמצאת בקטעים שסופקו.
   STATUS: NOT_FOUND - אם התשובה לא נמצאת בקטעים, או שהקטעים רק נוגעים בנושא בלי לענות על השאלה עצמה.
   חריג חשוב - שאלה על הפוליסה האישית של המשתמש (למשל "הפוליסה שלי מכסה את התאונה שהייתה לי?"):
   אם בקטעים יש מידע כללי על הנושא (למשל מה ביטוח מקיף מכסה), כתבי STATUS: FOUND, הסבירי מה כתוב באתר
   באופן כללי, וכתבי במפורש שאת הבדיקה של הפוליסה האישית עושים מול שירות הלקוחות. NOT_FOUND רק אם אין
   בקטעים שום מידע כללי על הנושא.
   אחרי השורה הזו כתבי את התשובה עצמה.
   במקרה של NOT_FOUND כתבי אחרי השורה תגובה קצרה וטבעית למשתמש, משפט או שניים, מותאמת לשאלה שלו.
   מותר בה רק: לומר בעדינות שבזה את לא יכולה לעזור, לומר שאת עוזרת בביטוח רכב, דירה ונסיעות לחו"ל
   ובשירות הלקוחות של הפניקס, ואם מתאים - להציע שאלה קשורה שאפשר לשאול אותך.
   אסור בה בהחלט: כל עובדה או מידע כללי על הנושא שנשאל (גם לא "בדרך כלל..."), מספרים, מחירים, תאריכים,
   שמות של חברות אחרות, וכתובות URL. פרטי הקשר של שירות הלקוחות יתווספו אוטומטית.
1. עני אך ורק לפי הקטעים שסופקו לך למטה, מתוך אתר הפניקס. אסור להמציא פרטים ואסור להשתמש בידע כללי שלך.
   אם קטע עוסק בתחום אחר מזה שנשאלת עליו, השתמשי בו רק אם הוא באמת רלוונטי לשאלה הנוכחית.
2. אם התשובה לא נמצאת בקטעים שסופקו - אמרי זאת במפורש ואל תנחשי, ואל תצייני שום כתובת URL באותו מקרה.
3. בסוף תשובה שמבוססת על מקור, כתבי בשורה נפרדת **את כתובות ה-URL של כל העמודים שבהם באמת נעזרת** -
   לא רק עמוד "ראשי" אחד. אם הסתמכת על כמה עמודים לפרטים שונים בתשובה (למשל גם רכב וגם דירה), ציטטי את
   כולם, כל כתובת בשורה משלה, בלי כותרת כמו "מקורות" ובלי מספור. רשימה מסודרת תוצג בנפרד על ידי המערכת.
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
    # Seen in the 2026-10-23 eval, from answers that said "no info" in other words but still cited URLs
    "אין תשובה ישירה",
    "לא סופקו לי",
    "אינם עוסקים בשאלה",
    "אין בהם מידע",
    "לא נמצא מחיר",
)


# The model must open with "STATUS: FOUND" or "STATUS: NOT_FOUND" (SYSTEM_PROMPT rule 0), so the
# code decides "is there an answer?" from an explicit flag instead of guessing from free-form
# Hebrew wording. Tolerates markdown bold / case / spacing, since models decorate that line.
_STATUS_RE = re.compile(r"^[\s*_`#>]*STATUS\s*:\s*[*_`]*\s*(NOT[_ ]FOUND|FOUND)\b[*_`]*", re.IGNORECASE)


def parse_status(answer_text: str) -> tuple[str | None, str]:
    """Return (status, body). status is "FOUND", "NOT_FOUND", or None if the first non-empty line
    isn't a status line. body is the answer with the status line removed."""
    lines = answer_text.strip().splitlines()
    if not lines:
        return None, ""
    m = _STATUS_RE.match(lines[0])
    if not m:
        return None, answer_text.strip()
    status = "NOT_FOUND" if m.group(1).upper().startswith("NOT") else "FOUND"
    return status, "\n".join(lines[1:]).strip()


# A NOT_FOUND reply is written by the model, so it's checked before it's shown: it may only say
# "I can't help with this, here's what I can help with". Anything that looks like content - a
# digit (prices, dates, phone numbers, temperatures), a URL, or more than a short message - fails
# the check, and the fixed NOT_ON_SITE_MESSAGE is shown instead. "תקלה" is blocked because the
# chat UI reads that word as an outage.
REFUSAL_MAX_CHARS = 260
REFUSAL_MAX_SENTENCES = 3
_BLOCKED_IN_REFUSAL = re.compile(r"\d|https?://|www\.|@|₪|%|\$|תקלה")


def safe_refusal(reply: str) -> str | None:
    """The model's own short refusal + the contact link, or None if it fails the safety check."""
    reply = reply.strip()
    if not reply or len(reply) > REFUSAL_MAX_CHARS or _BLOCKED_IN_REFUSAL.search(reply):
        return None
    sentences = [s for s in re.split(r"[.!?]+", reply) if s.strip()]
    if len(sentences) > REFUSAL_MAX_SENTENCES:
        return None
    return f"{reply}\nלפרטי הקשר עם שירות הלקוחות: {CONTACT_URL}"


def claims_not_found(answer_text: str) -> bool:
    return any(p in answer_text for p in _NOT_FOUND_PHRASES)


def is_grounded(answer_text: str, allowed_urls: set[str]) -> bool:
    """True only if the answer cites a URL it was actually given as a source (blocks invented
    links) and doesn't itself say the information isn't there (blocks a stray citation habit)."""
    if claims_not_found(answer_text):
        return False
    return any(u in allowed_urls for u in cited_urls(answer_text))
