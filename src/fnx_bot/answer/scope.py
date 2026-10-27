"""SPEC "Scope v1" enforced in code: the bot answers on car, apartment, travel and customer service.
Other Phoenix products are on the site but not crawled yet (until the bot is expanded to the rest of
the site), so a question about one gets a refusal naming that product - before any search, so a page
about a different product can't be taken as the answer (e.g. a travel insurance price for a health
insurance question, seen in the eval with a weaker model).

The product name in the reply comes from this table, never from the model, so it can't add facts.
"""
from __future__ import annotations

import re

from .prompt import CONTACT_URL

# (pattern, label shown to the user). Mortgage is deliberately NOT here: building insurance for a
# mortgage is apartment insurance, which is in scope.
_OUT_OF_SCOPE = [
    (r"ביטוח (ה)?בריאות|ביטוח שיניים|ביטוח (ה)?שיניים", "ביטוח בריאות"),
    (r"ביטוח (ה)?חיים|ביטוח מנהלים", "ביטוח חיים"),
    (r"סיעוד", "ביטוח סיעודי"),
    (r"פנסי", "פנסיה"),
    (r"קופ(ת|ות) (ה)?גמל|\bגמל\b", "קופות גמל"),
    (r"קרן (ה)?השתלמות|קרנות השתלמות", "קרן השתלמות"),
    (r"ביטוח (ל)?חיות מחמד|ביטוח (ל)?כלבים|ביטוח (ל)?חתולים", "ביטוח חיות מחמד"),
    (r"ביטוח (ל)?עס(ק|קים)|ביטוח העסק", "ביטוח לעסק"),
]
_OUT_OF_SCOPE = [(re.compile(p), label) for p, label in _OUT_OF_SCOPE]

# If the question also names an in-scope product, it isn't refused here (e.g. "health cover abroad"
# is a travel insurance question) - it goes through the normal search.
_IN_SCOPE = re.compile(r"רכב|דיר(ה|ות)|מבנה|תכולה|נסיע|חו\"?ל|טיס|מזווד|כבודה")


def out_of_scope_topic(question: str) -> str | None:
    """The out-of-scope product a question is about, or None if it may be in scope."""
    if _IN_SCOPE.search(question):
        return None
    for pattern, label in _OUT_OF_SCOPE:
        if pattern.search(question):
            return label
    return None


def out_of_scope_message(label: str) -> str:
    return (
        f"על {label} אני עדיין לא יודעת לענות. כרגע אני עוזרת בביטוח רכב, דירה ונסיעות לחו\"ל "
        f"ובשירות הלקוחות של הפניקס. בנושא הזה נציג ישמח לעזור: {CONTACT_URL}"
    )
