import hashlib


def chunk_id(repo_id: str, path: str, start_line: int, end_line: int, content: str) -> str:
    content_digest = hashlib.sha1(content.encode("utf-8")).hexdigest()
    key = f"{repo_id}|{path}|{start_line}|{end_line}|{content_digest}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]
