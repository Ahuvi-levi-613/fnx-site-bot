#!/usr/bin/env python3
"""Day-one Hebrew check: does the embedding model match Hebrew questions to the right Hebrew passage?

Needs GEMINI_API_KEY in .env. Prints, for each question, which passage scored highest.
The passages below are made-up test sentences, not content from the site.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:embedContent"

PASSAGES = [
    "כדי להגיש תביעה על נזקי מים בדירה יש לצלם את הנזק ולפנות למוקד התביעות.",
    "ביטוח נסיעות לחו\"ל מכסה הוצאות רפואיות בזמן שהייה מחוץ לישראל.",
    "ניתן להעביר את כספי קרן ההשתלמות למסלול השקעה אחר דרך האזור האישי.",
    "בתאונת דרכים יש לרשום את פרטי הנהג השני ולדווח לחברת הביטוח.",
]
QUESTIONS = [
    ("נשפך לי מים מהמזגן והרטיב את הפרקט, מה עושים?", 0),
    ("אני טס לאירופה, האם יש כיסוי אם אצטרך רופא?", 1),
    ("איך משנים מסלול בקרן השתלמות?", 2),
    ("מישהו פגע לי ברכב בחניה", 3),
]


def embed(text: str, task: str) -> list[float]:
    r = requests.post(
        URL,
        headers={"x-goog-api-key": KEY},
        json={"content": {"parts": [{"text": text}]}, "taskType": task},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["embedding"]["values"]


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def main() -> int:
    if not KEY:
        print("Missing GEMINI_API_KEY in .env")
        return 1
    pv = [embed(p, "RETRIEVAL_DOCUMENT") for p in PASSAGES]
    hits = 0
    for q, want in QUESTIONS:
        qv = embed(q, "RETRIEVAL_QUERY")
        scores = [cos(qv, v) for v in pv]
        best = max(range(len(scores)), key=scores.__getitem__)
        hits += best == want
        mark = "OK  " if best == want else "MISS"
        print(f"{mark} {q}\n     -> {PASSAGES[best][:60]}… ({scores[best]:.3f})")
    print(f"\n{hits}/{len(QUESTIONS)} matched ({MODEL})")
    return 0 if hits == len(QUESTIONS) else 2


if __name__ == "__main__":
    sys.exit(main())
