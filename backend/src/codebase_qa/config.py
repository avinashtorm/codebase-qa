from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from codebase_qa.ingestion.hygiene import DEFAULT_DOWNWEIGHT, DEFAULT_SKIP, HygieneRules


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    demo_password: str = ""
    demo_repo_url: str = ""

    data_dir: Path = Path("data")
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    chunker: str = "treesitter"
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "vector"
    hybrid_candidates: int = 50
    rrf_k: int = 60
    rerank: bool = False
    rerank_candidates: int = 30
    rerank_fusion: bool = False
    min_vector_score: float = 0.60
    min_rerank_score: float = 0.0
    top_k: int = 8
    clone_timeout_seconds: float = 120.0
    max_repo_size_mb: int = 200
    max_visitor_repos: int = 15
    repo_ttl_hours: float = 24.0
    index_per_visitor_per_day: int = 5
    ask_rate_limit_per_minute: int = 10
    ask_per_visitor_per_day: int = 30
    ask_daily_limit: int = 0
    trust_proxy: bool = False
    allow_local_repos: bool = False
    github_token: str = ""
    log_level: str = "INFO"
    llm_cache: bool = False
    overview: bool = True
    overview_max_files: int = 60
    overview_max_folders: int = 25
    overview_batch_size: int = 20
    overview_max_calls: int = 5
    overview_file_chars: int = 1200
    overview_k: int = 3
    hygiene: bool = True
    hygiene_extra_skip: list[str] = []
    hygiene_extra_downweight: list[str] = []
    downweight_factor: float = 0.9
    downweight_tests: bool = True
    max_json_kb: int = 50
    suggested_questions: bool = True
    routing: bool = True
    routing_llm: bool = True
    followup_rewrite: bool = True
    query_expansion: bool = False
    expansion_variants: int = 3
    expansion_original_weight: int = 4
    expansion_skip_above: float = 0.0
    parent_context: bool = False
    parent_max_lines: int = 100
    parent_window: int = 10
    call_context: bool = True
    call_max_functions: int = 4
    call_max_lines: int = 150
    self_check: bool = True
    self_check_action: Literal["remove", "flag"] = "remove"

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def refusal_thresholds(self) -> dict[str, float]:
        return {"vector": self.min_vector_score, "rerank": self.min_rerank_score}

    @property
    def bm25_dir(self) -> Path:
        return self.data_dir / "bm25"

    @property
    def hygiene_rules(self) -> HygieneRules:
        return HygieneRules(
            skip=DEFAULT_SKIP + tuple(self.hygiene_extra_skip),
            downweight=DEFAULT_DOWNWEIGHT + tuple(self.hygiene_extra_downweight),
            factor=self.downweight_factor,
            max_json_kb=self.max_json_kb,
            downweight_tests=self.downweight_tests,
            enabled=self.hygiene,
        )

    @property
    def overview_dir(self) -> Path:
        return self.data_dir / "overview"

    @property
    def llm_cache_dir(self) -> Path:
        return self.data_dir / "llm_cache"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "registry.json"

    @property
    def access_path(self) -> Path:
        return self.data_dir / "access.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
