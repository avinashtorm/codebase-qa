import time
from collections.abc import Callable

from google import genai
from google.genai import errors, types

from codebase_qa.generation.cache import ResponseCache
from codebase_qa.generation.citations import extract_citations
from codebase_qa.generation.prompt import SYSTEM_PROMPT, build_user_prompt
from codebase_qa.models import GeneratedAnswer, RetrievedChunk

RETRYABLE_STATUS_CODES = frozenset({429, 500, 503})


class GenerationError(RuntimeError):
    pass


class QuotaExhaustedError(GenerationError):
    pass


def is_daily_quota(exc: errors.APIError) -> bool:
    return exc.code == 429 and "PerDay" in str(exc)


class GeminiGenerator:
    def __init__(
        self,
        client: genai.Client,
        model: str,
        temperature: float = 0.0,
        max_attempts: int = 4,
        backoff_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
        cache: ResponseCache | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep
        self.cache = cache

    def generate(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        text = self.complete(build_user_prompt(question, context))
        return GeneratedAnswer(answer=text, citations=extract_citations(text))

    def complete(self, prompt: str) -> str:
        key = ResponseCache.key(self.model, str(self.temperature), SYSTEM_PROMPT, prompt)
        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            return cached
        text = self.request(prompt)
        if self.cache:
            self.cache.put(key, text)
        return text

    def request(self, prompt: str) -> str:
        config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=self.temperature)
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                return response.text or ""
            except errors.APIError as exc:
                if is_daily_quota(exc):
                    raise QuotaExhaustedError(f"daily quota exhausted for {self.model}") from exc
                if exc.code not in RETRYABLE_STATUS_CODES or attempt == self.max_attempts:
                    raise GenerationError(f"language model request failed with status {exc.code}") from exc
                self.sleep(self.backoff_seconds * 2 ** (attempt - 1))
        raise GenerationError("language model request failed")
