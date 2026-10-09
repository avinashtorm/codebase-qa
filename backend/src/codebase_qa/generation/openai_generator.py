from openai import APIError, OpenAI

from codebase_qa.generation.citations import extract_citations
from codebase_qa.generation.prompt import SYSTEM_PROMPT, build_user_prompt
from codebase_qa.models import GeneratedAnswer, RetrievedChunk


class GenerationError(RuntimeError):
    pass


class OpenAIGenerator:
    def __init__(self, client: OpenAI, model: str, temperature: float = 0.0) -> None:
        self.client = client
        self.model = model
        self.temperature = temperature

    def generate(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(question, context)},
                ],
            )
        except APIError as exc:
            raise GenerationError(f"language model request failed: {type(exc).__name__}") from exc
        text = response.choices[0].message.content or ""
        return GeneratedAnswer(answer=text, citations=extract_citations(text))
