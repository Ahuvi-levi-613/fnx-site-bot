"""Day 3 chat server: one endpoint over the Day 2 answer pipeline.

GET  /            -> temporary plain test page (real design comes separately)
POST /api/chat     -> {question, history, area} -> {answer, sources, grounded}
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..answer.llm import LLMClient
from ..answer.pipeline import AnswerPipeline
from ..answer.rerank import CohereReranker
from ..answer.retrieve import HybridRetriever
from ..config import DATA_DIR

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="fnx-site-bot")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_pipeline: AnswerPipeline | None = None


def get_pipeline() -> AnswerPipeline:
    """Built once, on first request, so importing this module needs no API keys or index."""
    global _pipeline
    if _pipeline is None:
        from ..index.embed import VoyageEmbedder  # deferred: this branch alone has no VoyageEmbedder
        from ..index.store import ChromaStore

        embedder = VoyageEmbedder(cache_path=DATA_DIR / "embeddings_cache.jsonl")
        _pipeline = AnswerPipeline(
            retriever=HybridRetriever(embedder, ChromaStore()),
            reranker=CohereReranker(),
            llm=LLMClient(),
        )
    return _pipeline


class Turn(BaseModel):
    question: str
    answer: str


class ChatRequest(BaseModel):
    question: str
    history: list[Turn] = []
    area: str | None = None


class SourceOut(BaseModel):
    url: str
    page_title: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    grounded: bool


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, pipeline: AnswerPipeline = Depends(get_pipeline)) -> ChatResponse:
    history = [t.model_dump() for t in req.history] or None
    result = pipeline.answer(req.question, area=req.area, history=history)
    return ChatResponse(
        answer=result.text,
        sources=[SourceOut(url=s.url, page_title=s.page_title) for s in result.sources],
        grounded=result.grounded,
    )
