import argparse
from pathlib import Path

from eval.dataset import EvalQuestion, Location, load_questions

DEFAULT_REPO_DIR = Path("data/repos/fastapi__full-stack-fastapi-template")
FENCE_LANGUAGES = {".py": "python", ".ts": "ts", ".tsx": "tsx", ".yml": "yaml", ".sh": "bash"}


def github_link(repo_url: str, sha: str, location: Location) -> str:
    return f"{repo_url}/blob/{sha}/{location.path}#L{location.start_line}-L{location.end_line}"


def snippet(repo_dir: Path, location: Location) -> str:
    lines = (repo_dir / location.path).read_text(encoding="utf-8").splitlines()
    width = len(str(location.end_line))
    numbers = range(location.start_line, location.end_line + 1)
    numbered = [f"{number:>{width}}  {lines[number - 1]}" for number in numbers]
    language = FENCE_LANGUAGES.get(Path(location.path).suffix, "")
    return f"```{language}\n" + "\n".join(numbered) + "\n```"


def render_question(question: EvalQuestion, repo_dir: Path, repo_url: str, sha: str) -> str:
    parts = [f"## {question.id} [{question.category}] {question.question}", ""]
    for location in question.expected_locations:
        span = f"{location.path}:{location.start_line}-{location.end_line}"
        parts += [f"[{span}]({github_link(repo_url, sha, location)})", "", snippet(repo_dir, location), ""]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render questions with expected code for review")
    parser.add_argument("--questions", type=Path, default=Path("eval/candidates.jsonl"))
    parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    parser.add_argument("--repo-url", default="https://github.com/fastapi/full-stack-fastapi-template")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", type=Path, default=Path("eval/candidates_review.md"))
    args = parser.parse_args(argv)
    questions = load_questions(args.questions, split="all")
    header = f"# Candidate review\n\nRepo commit `{args.sha}`. {len(questions)} questions.\n"
    body = [render_question(question, args.repo_dir, args.repo_url, args.sha) for question in questions]
    args.out.write_text(header + "\n" + "\n".join(body), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
