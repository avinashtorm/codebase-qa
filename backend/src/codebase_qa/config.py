from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    max_repos: int = 5
    ask_rate_limit_per_minute: int = 10
    index_rate_limit_per_hour: int = 10
    trust_proxy: bool = False
    allow_local_repos: bool = False
    github_token: str = ""
    log_level: str = "INFO"
    llm_cache: bool = False

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
    def llm_cache_dir(self) -> Path:
        return self.data_dir / "llm_cache"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "registry.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
