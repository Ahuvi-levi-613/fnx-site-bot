#!/usr/bin/env python3
"""Day 4: run eval/questions.json against the real pipeline and score it against the SPEC
targets (accuracy, refusal, source correctness, follow-ups).

  python scripts/run_eval.py                 # run everything, print a report
  python scripts/run_eval.py --save out.json  # also save raw results for inspection

Needs the same keys as scripts/ask.py, plus a built index.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

from fnx_bot.answer.llm import LLMClient  # noqa: E402
from fnx_bot.answer.pipeline import AnswerPipeline  # noqa: E402
from fnx_bot.answer.prompt import NOT_ON_SITE_MESSAGE, SERVICE_UNAVAILABLE_MESSAGE  # noqa: E402
from fnx_bot.answer.rerank import CohereReranker  # noqa: E402
from fnx_bot.answer.retrieve import HybridRetriever  # noqa: E402
from fnx_bot.config import DATA_DIR, ROOT  # noqa: E402
from fnx_bot.index.embed import VoyageEmbedder  # noqa: E402
from fnx_bot.index.store import ChromaStore  # noqa: E402

QUESTIONS_PATH = ROOT / "eval" / "questions.json"
REFERRAL_PHRASES = ("שירות הלקוחות", "נציג", "מוקד")

# Cohere's trial rerank key caps at 10 requests/min; a run of 30+ un-paced calls hits that
# almost immediately and cascades into spurious SERVICE_UNAVAILABLE results that have nothing
# to do with answer quality. Pace calls, and retry a question once or twice before accepting
# an infra hiccup as a real result.
PACE_SECONDS = 7
RETRY_PAUSE_SECONDS = 15
MAX_RETRIES = 2


class Pacer:
    def __init__(self, seconds: float):
        self.seconds = seconds
        self._first = True

    def wait(self) -> None:
        if self._first:
            self._first = False
        else:
            time.sleep(self.seconds)


def load_questions() -> dict:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def answer_with_retry(pipeline: AnswerPipeline, pacer: Pacer, question: str, *, area=None, history=None):
    pacer.wait()
    r = pipeline.answer(question, area=area, history=history)
    attempt = 0
    while r.text == SERVICE_UNAVAILABLE_MESSAGE and attempt < MAX_RETRIES:
        attempt += 1
        print(f"    (infra hiccup, retry {attempt}/{MAX_RETRIES} in {RETRY_PAUSE_SECONDS}s...)")
        time.sleep(RETRY_PAUSE_SECONDS)
        r = pipeline.answer(question, area=area, history=history)
    return r


def run_answerable(pipeline: AnswerPipeline, pacer: Pacer, items: list[dict]) -> list[dict]:
    results = []
    for q in items:
        r = answer_with_retry(pipeline, pacer, q["question"], area=q.get("area"))
        source_urls = [s.url for s in r.sources]
        correct = r.grounded and q["expected_url"] in source_urls
        results.append({
            "id": q["id"], "question": q["question"], "expected_url": q["expected_url"],
            "grounded": r.grounded, "source_urls": source_urls, "correct": correct,
            "answer": r.text,
        })
    return results


def run_not_answerable(pipeline: AnswerPipeline, pacer: Pacer, items: list[dict]) -> list[dict]:
    results = []
    for q in items:
        r = answer_with_retry(pipeline, pacer, q["question"])
        correct = (not r.grounded) and r.text == NOT_ON_SITE_MESSAGE
        results.append({
            "id": q["id"], "question": q["question"], "grounded": r.grounded,
            "correct": correct, "answer": r.text,
        })
    return results


def run_personal_policy(pipeline: AnswerPipeline, pacer: Pacer, items: list[dict]) -> list[dict]:
    """Soft check: either a clean refusal, or an answer that refers to customer service
    (not a strict source match - the right behavior per SPEC is "explain generally, refer
    for the personal specifics", which doesn't have one fixed expected URL)."""
    results = []
    for q in items:
        r = answer_with_retry(pipeline, pacer, q["question"])
        has_referral = any(p in r.text for p in REFERRAL_PHRASES)
        acceptable = (not r.grounded) or has_referral
        results.append({
            "id": q["id"], "question": q["question"], "grounded": r.grounded,
            "acceptable": acceptable, "answer": r.text,
        })
    return results


def run_follow_ups(pipeline: AnswerPipeline, pacer: Pacer, items: list[dict]) -> list[dict]:
    results = []
    for d in items:
        r1 = answer_with_retry(pipeline, pacer, d["turn1"], area=d.get("area"))
        history = [{"question": d["turn1"], "answer": r1.text}]
        r2 = answer_with_retry(pipeline, pacer, d["turn2"], history=history)
        understood = r2.grounded or any(p in r2.text for p in REFERRAL_PHRASES)
        results.append({
            "id": d["id"], "turn1": d["turn1"], "turn2": d["turn2"],
            "turn1_grounded": r1.grounded, "turn2_grounded": r2.grounded,
            "turn2_sources": [s.url for s in r2.sources], "understood": understood,
            "turn1_answer": r1.text, "turn2_answer": r2.text,
        })
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--save", help="also write full raw results to this JSON file")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    embedder = VoyageEmbedder(cache_path=DATA_DIR / "embeddings_cache.jsonl")
    pipeline = AnswerPipeline(
        retriever=HybridRetriever(embedder, ChromaStore()),
        reranker=CohereReranker(),
        llm=LLMClient(),
    )

    data = load_questions()
    pacer = Pacer(PACE_SECONDS)
    t0 = time.time()

    print(f"Running {len(data['answerable'])} answerable questions...")
    answerable = run_answerable(pipeline, pacer, data["answerable"])

    print(f"Running {len(data['not_answerable'])} not-answerable questions...")
    not_answerable = run_not_answerable(pipeline, pacer, data["not_answerable"])

    print(f"Running {len(data['personal_policy'])} personal-policy questions...")
    personal_policy = run_personal_policy(pipeline, pacer, data["personal_policy"])

    print(f"Running {len(data['follow_ups'])} follow-up dialogs...")
    follow_ups = run_follow_ups(pipeline, pacer, data["follow_ups"])

    elapsed = time.time() - t0

    acc_n = sum(r["correct"] for r in answerable)
    refuse_n = sum(r["correct"] for r in not_answerable)
    policy_n = sum(r["acceptable"] for r in personal_policy)
    followup_n = sum(r["understood"] for r in follow_ups)

    print("\n" + "=" * 60)
    print("SPEC targets:")
    print(f"  Accuracy (answerable):        {acc_n}/{len(answerable)}  (target 18/20)")
    print(f"  Correct refusal + contact:    {refuse_n}/{len(not_answerable)}  (target 10/10)")
    print(f"  Personal-policy handled ok:   {policy_n}/{len(personal_policy)}  (no fixed target)")
    print(f"  Follow-ups understood:        {followup_n}/{len(follow_ups)}  (target 5/5)")
    print(f"  (took {elapsed:.0f}s)")
    print("=" * 60)

    print("\nFailures (answerable):")
    for r in answerable:
        if not r["correct"]:
            print(f"  [{r['id']}] {r['question']}")
            print(f"    expected: {r['expected_url']}")
            print(f"    got sources: {r['source_urls']} grounded={r['grounded']}")

    print("\nFailures (not-answerable, should have been refused):")
    for r in not_answerable:
        if not r["correct"]:
            print(f"  [{r['id']}] {r['question']} -> grounded={r['grounded']}")
            print(f"    {r['answer'][:160]}")

    print("\nFailures (personal-policy, should refuse or refer):")
    for r in personal_policy:
        if not r["acceptable"]:
            print(f"  [{r['id']}] {r['question']}")
            print(f"    {r['answer'][:160]}")

    print("\nFailures (follow-ups):")
    for r in follow_ups:
        if not r["understood"]:
            print(f"  [{r['id']}] turn1={r['turn1']!r} turn2={r['turn2']!r}")
            print(f"    turn2 answer: {r['turn2_answer'][:160]}")

    if args.save:
        out_path = Path(args.save)
        out_path.write_text(
            json.dumps({
                "answerable": answerable, "not_answerable": not_answerable,
                "personal_policy": personal_policy, "follow_ups": follow_ups,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nSaved raw results to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
