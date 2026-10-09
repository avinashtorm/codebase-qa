import argparse
import json
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from codebase_qa.config import Settings
from codebase_qa.container import Container
from codebase_qa.fs import remove_tree
from codebase_qa.indexing.registry import RepoRecord
from eval.run import DEFAULT_REPO_URL, RESULTS_DIR

BENCH_DIR = Path("data/bench")


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True)
    return result.stdout.strip()


def chunk_ids(container: Container, record: RepoRecord) -> list[str]:
    return sorted(chunk.chunk_id for chunk in container.store.collection(record.collection).all_chunks())


def timed_index(container: Container, url: str) -> tuple[RepoRecord, float]:
    started = time.perf_counter()
    record = container.indexer.index(url)
    return record, round(time.perf_counter() - started, 2)


def prepare_origin(upstream_url: str, commits_back: int) -> tuple[Path, str, str]:
    upstream = BENCH_DIR / "upstream"
    if not upstream.exists():
        BENCH_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "60", upstream_url, str(upstream)], check=True)
    origin = BENCH_DIR / "origin"
    remove_tree(origin)
    subprocess.run(["git", "clone", "-q", str(upstream.resolve()), str(origin)], check=True)
    new_sha = git(origin, "rev-parse", "HEAD")
    git(origin, "reset", "-q", "--hard", f"HEAD~{commits_back}")
    return origin, git(origin, "rev-parse", "HEAD"), new_sha


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Benchmark incremental re-indexing against a full rebuild")
    parser.add_argument("--commits-back", type=int, default=10)
    parser.add_argument("--chunker", default="treesitter")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    args = parser.parse_args(argv)

    origin, old_sha, new_sha = prepare_origin(args.repo_url, args.commits_back)
    for name in ("incremental", "full"):
        remove_tree(BENCH_DIR / name)
    incremental = Container(Settings(data_dir=BENCH_DIR / "incremental", chunker=args.chunker))
    full = Container(Settings(data_dir=BENCH_DIR / "full", chunker=args.chunker))
    full.embedder = incremental.embedder

    record, old_full_seconds = timed_index(incremental, origin.resolve().as_uri())
    git(origin, "reset", "-q", "--hard", new_sha)
    updated, report = incremental.indexer.reindex(record)
    rebuilt, new_full_seconds = timed_index(full, origin.resolve().as_uri())

    identical = chunk_ids(incremental, updated) == chunk_ids(full, rebuilt)
    payload = {
        "config": "reindex-benchmark",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "repo": args.repo_url,
        "old_sha": old_sha,
        "new_sha": new_sha,
        "commits_between": args.commits_back,
        "chunker": args.chunker,
        "full_index_seconds_old": old_full_seconds,
        "full_index_seconds_new": new_full_seconds,
        "incremental_seconds": report.seconds,
        "speedup": round(new_full_seconds / report.seconds, 1) if report.seconds else None,
        "report": asdict(report) | {"files_changed": report.files_changed},
        "total_files": rebuilt.file_count,
        "total_chunks": rebuilt.chunk_count,
        "identical_to_full_rebuild": identical,
    }
    path = RESULTS_DIR / f"reindex-benchmark_{payload['timestamp'].replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(json.dumps(payload, indent=1))
    print(f"saved {path}")


if __name__ == "__main__":
    main()
