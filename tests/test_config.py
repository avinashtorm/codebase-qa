from pathlib import Path

import pytest

from codebase_qa.config import Settings


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    assert settings.gemini_model == "test-model"
    assert settings.repos_dir == tmp_path / "repos"
    assert settings.chroma_dir == tmp_path / "chroma"
