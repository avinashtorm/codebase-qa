import json

from pydantic import BaseModel, Field, ValidationError

from codebase_qa.generation.citations import extract_citations
from codebase_qa.generation.prompt import build_user_prompt, system_prompt_for
from codebase_qa.interfaces import LLM
from codebase_qa.models import Citation, GeneratedAnswer, RetrievedChunk


class CitationSchema(BaseModel):
    path: str = Field(description="file path exactly as written in a context label")
    start_line: int = Field(description="first cited line, inside the labelled block")
    end_line: int = Field(description="last cited line, inside the labelled block")


class AnswerSchema(BaseModel):
    answer: str = Field(description="concise markdown answer")
    citations: list[CitationSchema] = Field(description="code locations that support the answer")


def parse_answer(text: str) -> GeneratedAnswer:
    try:
        payload = AnswerSchema.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError):
        return GeneratedAnswer(answer=text, citations=extract_citations(text))
    citations = [Citation(c.path, c.start_line, c.end_line) for c in payload.citations]
    return GeneratedAnswer(answer=payload.answer, citations=citations)


class LLMGenerator:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def generate(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        prompt = build_user_prompt(question, context)
        response = self.llm.complete(system_prompt_for(context), prompt, AnswerSchema)
        return parse_answer(response.text)
