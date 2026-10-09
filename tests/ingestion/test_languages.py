import pytest

from codebase_qa.ingestion.languages import detect_language


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/b.py", "python"),
        ("x.TS", "typescript"),
        ("ui/App.tsx", "tsx"),
        ("main.go", "go"),
        ("Foo.java", "java"),
        ("Dockerfile", "dockerfile"),
        ("backend/Dockerfile.prod", "dockerfile"),
        (".env.example", "dotenv"),
        ("image.png", None),
    ],
)
def test_detect_language(path: str, expected: str | None) -> None:
    assert detect_language(path) == expected
