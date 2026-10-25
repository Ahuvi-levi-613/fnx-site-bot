import pytest
from fastapi.testclient import TestClient

from fnx_bot.answer.pipeline import AnswerResult, Source
from fnx_bot.server.app import app, get_pipeline


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


class FakePipeline:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def answer(self, question, area=None, history=None):
        self.calls.append({"question": question, "area": area, "history": history})
        return self._result


def test_chat_endpoint_returns_answer_and_sources():
    fake = FakePipeline(AnswerResult(text="תשובה", sources=[Source(url="https://x", page_title="t")], grounded=True))
    app.dependency_overrides[get_pipeline] = lambda: fake
    client = TestClient(app)

    r = client.post("/api/chat", json={"question": "שאלה?"})

    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "תשובה"
    assert body["grounded"] is True
    assert body["sources"] == [{"url": "https://x", "page_title": "t"}]


def test_chat_endpoint_passes_history_and_area_through():
    fake = FakePipeline(AnswerResult(text="x", sources=[], grounded=False))
    app.dependency_overrides[get_pipeline] = lambda: fake
    client = TestClient(app)

    client.post(
        "/api/chat",
        json={
            "question": "ומה עם רכב?",
            "area": "car",
            "history": [{"question": "שאלה קודמת", "answer": "תשובה קודמת"}],
        },
    )

    assert fake.calls[0]["question"] == "ומה עם רכב?"
    assert fake.calls[0]["area"] == "car"
    assert fake.calls[0]["history"] == [{"question": "שאלה קודמת", "answer": "תשובה קודמת"}]


def test_chat_endpoint_no_history_passes_none():
    fake = FakePipeline(AnswerResult(text="x", sources=[], grounded=False))
    app.dependency_overrides[get_pipeline] = lambda: fake
    client = TestClient(app)

    client.post("/api/chat", json={"question": "שאלה"})

    assert fake.calls[0]["history"] is None


def test_index_page_served():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_chat_endpoint_returns_provider_and_logs_it_without_the_question(caplog):
    fake = FakePipeline(AnswerResult(text="תשובה", sources=[], grounded=True, provider="gemini"))
    app.dependency_overrides[get_pipeline] = lambda: fake
    client = TestClient(app)

    with caplog.at_level("INFO", logger="uvicorn.error"):
        r = client.post("/api/chat", json={"question": "שאלה סודית?"})

    assert r.json()["provider"] == "gemini"
    assert "provider=gemini" in caplog.text
    assert "שאלה סודית" not in caplog.text  # privacy: the question itself is never logged
