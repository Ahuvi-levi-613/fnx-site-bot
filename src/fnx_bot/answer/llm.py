"""LLM client with automatic fallback: Gemini Flash -> Groq -> OpenRouter (SPEC: on
failure, wait then fall through so the user shouldn't notice)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    pass


@dataclass
class LLMResponse:
    text: str
    provider: str  # "gemini", "groq", or "openrouter" -- whichever answered


class LLMClient:
    """Generates a chat completion from a system + user prompt, trying Gemini Flash first
    and falling back to Groq, then OpenRouter, if a provider errors (quota, outage, etc)."""

    def __init__(
        self,
        gemini_api_key: str | None = None,
        groq_api_key: str | None = None,
        openrouter_api_key: str | None = None,
        gemini_model: str | None = None,
        groq_model: str | None = None,
        openrouter_model: str | None = None,
        retry_pause: float = 1.0,
        session: requests.Session | None = None,
    ):
        self.gemini_api_key = (gemini_api_key if gemini_api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.groq_api_key = (groq_api_key if groq_api_key is not None else os.getenv("GROQ_API_KEY", "")).strip()
        self.openrouter_api_key = (
            openrouter_api_key if openrouter_api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        ).strip()
        self.gemini_model = gemini_model or os.getenv("GEMINI_LLM_MODEL", "gemini-3.6-flash")
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.openrouter_model = openrouter_model or os.getenv(
            "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
        )
        self.retry_pause = retry_pause
        self.session = session or requests.Session()

    def _gemini(self, system: str, prompt: str) -> str:
        if not self.gemini_api_key:
            raise LLMError("Missing GEMINI_API_KEY in .env")
        url = f"{GEMINI_API}/{self.gemini_model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system}]},
        }
        r = self.session.post(url, headers={"x-goog-api-key": self.gemini_api_key}, json=body, timeout=60)
        if not r.ok:
            raise LLMError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _openai_compatible(self, api_key: str, url: str, model: str, system: str, prompt: str, provider: str) -> str:
        if not api_key:
            raise LLMError(f"Missing API key for {provider}")
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        r = self.session.post(
            url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body, timeout=60
        )
        if not r.ok:
            raise LLMError(f"{provider} HTTP {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]

    def generate(self, system: str, prompt: str) -> LLMResponse:
        """Try Gemini, then Groq, then OpenRouter. Raises LLMError only if all three fail."""
        errors = []
        providers = (
            ("gemini", lambda: self._gemini(system, prompt)),
            ("groq", lambda: self._openai_compatible(self.groq_api_key, GROQ_API, self.groq_model, system, prompt, "groq")),
            (
                "openrouter",
                lambda: self._openai_compatible(
                    self.openrouter_api_key, OPENROUTER_API, self.openrouter_model, system, prompt, "openrouter"
                ),
            ),
        )
        for provider, call in providers:
            try:
                return LLMResponse(text=call(), provider=provider)
            except (LLMError, requests.RequestException) as e:
                errors.append(f"{provider}: {e}")
                if provider != providers[-1][0]:
                    time.sleep(self.retry_pause)  # brief pause before falling through to the next provider
        raise LLMError("All providers failed: " + " | ".join(errors))
