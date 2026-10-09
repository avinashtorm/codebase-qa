from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    demo_password: str = ""
    demo_repo_url: str = ""

    data_dir: Path = Path("data")
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    chunker: str = "fixed"
    top_k: int = 8
    clone_timeout_seconds: float = 120.0

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "registry.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
