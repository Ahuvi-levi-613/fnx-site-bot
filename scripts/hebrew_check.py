#!/usr/bin/env python3
"""Day-one Hebrew check: do the embeddings match Hebrew questions to the right Hebrew passage?

Needs VOYAGE_API_KEY in .env. Prints, for each question, which passage scored highest.
The passages below are made-up test sentences, not content from the site.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Hebrew output on a Windows console that isn't UTF-8 would otherwise crash.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

from fnx_bot.config import ROOT  # noqa: E402
from fnx_bot.index.embed import EmbedError, VoyageEmbedder  # noqa: E402

PASSAGES = [
    "כדי להגיש תביעה על נזקי מים בדירה יש לצלם את הנזק ולפנות למוקד התביעות.",
    "ביטוח נסיעות לחו\"ל מכסה הוצאות רפואיות בזמן שהייה מחוץ לישראל.",
    "ניתן לפנות לשירות הלקוחות בטלפון, בוואטסאפ או בטופס צור קשר באתר.",
    "בתאונת דרכים יש לרשום את פרטי הנהג השני ולדווח לחברת הביטוח.",
]
QUESTIONS = [
    ("נשפכו מים מהמזגן והרטיבו את הפרקט, מה עושים?", 0),
    ("אני טס לאירופה, האם יש כיסוי אם אצטרך רופא?", 1),
    ("איך אפשר לדבר עם נציג?", 2),
    ("מישהו פגע לי ברכב בחניה", 3),
]


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def main() -> int:
    load_dotenv(ROOT / ".env")
    emb = VoyageEmbedder()
    try:
        pv = emb.embed_many(PASSAGES, input_type="document")
        qv = emb.embed_many([q for q, _ in QUESTIONS], input_type="query")
    except EmbedError as e:
        print(f"Error: {e}")
        return 1
    hits = 0
    for (q, want), v in zip(QUESTIONS, qv):
        scores = [cos(v, p) for p in pv]
        best = max(range(len(scores)), key=scores.__getitem__)
        hits += best == want
        print(f"{'OK  ' if best == want else 'MISS'} {q}\n     -> {PASSAGES[best][:60]}… ({scores[best]:.3f})")
    print(f"\n{hits}/{len(QUESTIONS)} matched ({emb.model})")
    return 0 if hits == len(QUESTIONS) else 2


if __name__ == "__main__":
    sys.exit(main())
