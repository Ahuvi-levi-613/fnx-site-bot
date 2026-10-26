"""LLM client with automatic fallback: a chain of Gemini models -> Groq (SPEC: on failure, fall
through so the user shouldn't notice).

Gemini's free quota is counted per model, so a second Gemini model is a free, good-Hebrew backup
on the same key. OpenRouter was dropped (2026-10-25): its free model wrote broken Hebrew and once
echoed prompt text to the user - a clear "temporary outage" message is better than that.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"

# Tested 2026-10-25 on real eval questions: 3.6-flash is the best; 3.5-flash-lite gave good,
# grounded Hebrew and has its own quota. (3.8/3.5-flash were overloaded or out of quota,
# 2.5-flash is closed to new users.)
DEFAULT_GEMINI_MODELS = ("gemini-3.6-flash", "gemini-3.5-flash-lite")
# llama-3.3-70b-versatile is no longer offered by Groq (checked 2026-10-25 via GET /models).
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


def _to_gemini_schema(schema: dict) -> dict:
    """Standard JSON Schema -> the OpenAPI-style subset Gemini's responseSchema takes
    (upper-case type names, no additionalProperties)."""
    out = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type":
            out[key] = value.upper()
        elif key == "properties":
            out[key] = {name: _to_gemini_schema(sub) for name, sub in value.items()}
            out["propertyOrdering"] = list(value)
        elif key == "items":
            out[key] = _to_gemini_schema(value)
        else:
            out[key] = value
    return out


class LLMError(Exception):
    pass


@dataclass
class LLMResponse:
    text: str
    provider: str  # whoever answered: "gemini:<model>" or "groq"


def _gemini_models_from_env() -> list[str]:
    """GEMINI_LLM_MODELS (comma-separated chain) wins. An older .env with only GEMINI_LLM_MODEL
    keeps that model first and still gets the default backup after it."""
    chain = os.getenv("GEMINI_LLM_MODELS", "").strip()
    if chain:
        return [m.strip() for m in chain.split(",") if m.strip()]
    single = os.getenv("GEMINI_LLM_MODEL", "").strip()
    if single:
        return [single] + [m for m in DEFAULT_GEMINI_MODELS if m != single]
    return list(DEFAULT_GEMINI_MODELS)


class LLMClient:
    """Generates a reply from a system + user prompt: each Gemini model in order, then Groq,
    moving on whenever one errors (quota, overload, timeout, missing key)."""

    def __init__(
        self,
        gemini_api_key: str | None = None,
        groq_api_key: str | None = None,
        gemini_models: list[str] | None = None,
        groq_model: str | None = None,
        retry_pause: float = 1.0,
        session: requests.Session | None = None,
    ):
        self.gemini_api_key = (gemini_api_key if gemini_api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.groq_api_key = (groq_api_key if groq_api_key is not None else os.getenv("GROQ_API_KEY", "")).strip()
        self.gemini_models = list(gemini_models) if gemini_models else _gemini_models_from_env()
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "") or DEFAULT_GROQ_MODEL
        self.retry_pause = retry_pause
        self.session = session or requests.Session()

    def _gemini(self, system: str, prompt: str, model: str | None = None, schema: dict | None = None) -> str:
        if not self.gemini_api_key:
            raise LLMError("Missing GEMINI_API_KEY in .env")
        url = f"{GEMINI_API}/{model or self.gemini_models[0]}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system}]},
        }
        if schema:
            # Structured output: Gemini must return JSON matching the schema (enforced by the API)
            body["generationConfig"] = {"responseMimeType": "application/json", "responseSchema": _to_gemini_schema(schema)}
        r = self.session.post(url, headers={"x-goog-api-key": self.gemini_api_key}, json=body, timeout=60)
        if not r.ok:
            raise LLMError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _groq(self, system: str, prompt: str, schema: dict | None = None) -> str:
        if not self.groq_api_key:
            raise LLMError("Missing GROQ_API_KEY")
        body = {
            "model": self.groq_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}
        r = self.session.post(
            GROQ_API,
            headers={"Authorization": f"Bearer {self.groq_api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        if not r.ok:
            raise LLMError(f"groq HTTP {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]

    def generate(self, system: str, prompt: str, schema: dict | None = None) -> LLMResponse:
        """Try each Gemini model, then Groq. Raises LLMError only if every one fails.
        schema: an optional JSON Schema the reply must follow (structured output)."""
        steps = [(f"gemini:{m}", lambda m=m: self._gemini(system, prompt, m, schema)) for m in self.gemini_models]
        steps.append(("groq", lambda: self._groq(system, prompt, schema)))
        errors = []
        for i, (provider, call) in enumerate(steps):
            try:
                return LLMResponse(text=call(), provider=provider)
            except (LLMError, requests.RequestException, KeyError, IndexError) as e:
                # KeyError/IndexError: a 200 reply without text (e.g. a blocked response)
                errors.append(f"{provider}: {e}")
                if i < len(steps) - 1:
                    time.sleep(self.retry_pause)
        raise LLMError("All providers failed: " + " | ".join(errors))
