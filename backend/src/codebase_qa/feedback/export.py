import argparse
from pathlib import Path

from codebase_qa.config import get_settings
from codebase_qa.feedback.store import FeedbackStore, export_jsonl


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export answer feedback (thumbs up/down) to a JSONL file")
    parser.add_argument("--out", type=Path, default=Path("feedback.jsonl"))
    parser.add_argument("--db", type=Path, default=None, help="feedback database (default: DATA_DIR/feedback.sqlite3)")
    args = parser.parse_args(argv)
    store = FeedbackStore(args.db or get_settings().feedback_path)
    count = export_jsonl(store, args.out)
    print(f"exported {count} feedback rows to {args.out}")


if __name__ == "__main__":
    main()
