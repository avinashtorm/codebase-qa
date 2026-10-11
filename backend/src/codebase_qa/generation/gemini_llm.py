import json
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from codebase_qa.generation.cache import ResponseCache
from codebase_qa.generation.llm import GenerationError, LLMResponse, QuotaExhaustedError

RETRYABLE_STATUS_CODES = frozenset({429, 500, 503})
CACHE_VERSION = "llm-v2"


def is_daily_quota(exc: errors.APIError) -> bool:
    return exc.code == 429 and "PerDay" in str(exc)


def schema_signature(schema: type[BaseModel] | None) -> str:
    return "" if schema is None else json.dumps(schema.model_json_schema(), sort_keys=True)


def token_counts(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    return int(getattr(usage, "prompt_token_count", 0) or 0), int(getattr(usage, "candidates_token_count", 0) or 0)


class GeminiLLM:
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

    def cache_key(self, system: str, prompt: str, schema: type[BaseModel] | None) -> str:
        return ResponseCache.key(
            CACHE_VERSION, self.model, str(self.temperature), schema_signature(schema), system, prompt
        )

    def complete(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> LLMResponse:
        key = self.cache_key(system, prompt, schema)
        entry = self.cache.get_entry(key) if self.cache else None
        if entry is not None:
            return LLMResponse(
                text=str(entry["text"]),
                input_tokens=int(entry.get("input_tokens", 0)),
                output_tokens=int(entry.get("output_tokens", 0)),
                cached=True,
            )
        response = self.request(system, prompt, schema)
        if self.cache:
            self.cache.put(
                key, response.text, input_tokens=response.input_tokens, output_tokens=response.output_tokens
            )
        return response

    def config(self, system: str, schema: type[BaseModel] | None) -> types.GenerateContentConfig:
        if schema is None:
            return types.GenerateContentConfig(system_instruction=system, temperature=self.temperature)
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            response_mime_type="application/json",
            response_schema=schema,
        )

    def request(self, system: str, prompt: str, schema: type[BaseModel] | None) -> LLMResponse:
        config = self.config(system, schema)
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
                input_tokens, output_tokens = token_counts(response)
                return LLMResponse(response.text or "", input_tokens, output_tokens)
            except errors.APIError as exc:
                if is_daily_quota(exc):
                    raise QuotaExhaustedError(f"daily quota exhausted for {self.model}") from exc
                if exc.code not in RETRYABLE_STATUS_CODES or attempt == self.max_attempts:
                    raise GenerationError(f"language model request failed with status {exc.code}") from exc
                self.sleep(self.backoff_seconds * 2 ** (attempt - 1))
        raise GenerationError("language model request failed")
