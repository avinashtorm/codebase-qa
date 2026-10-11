import json
from collections.abc import Iterator
from typing import Any

import httpx


class BackendError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def error_detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except ValueError:
        return response.text


def ask_payload(
    repo_id: str, question: str, history: list[dict[str, str]] | None, filters: dict[str, Any] | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"repo_id": repo_id, "question": question, "history": history or []}
    if filters and (filters.get("folder") or filters.get("languages")):
        payload["filters"] = filters
    return payload


class BackendClient:
    def __init__(
        self,
        base_url: str,
        password: str = "",
        client_ip: str = "",
        transport: httpx.BaseTransport | None = None,
        visitor_id: str = "",
    ) -> None:
        headers = {"X-Demo-Password": password} if password else {}
        if client_ip:
            headers["X-Forwarded-For"] = client_ip
        if visitor_id:
            headers["X-Visitor-Id"] = visitor_id
        self.http = httpx.Client(base_url=base_url, headers=headers, timeout=120.0, transport=transport)

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BackendError(f"backend is not reachable ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise BackendError(error_detail(response), response.status_code)
        return response.json()

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/health")

    def repos(self) -> list[dict[str, Any]]:
        return self.request("GET", "/repos")

    def index(self, url: str) -> dict[str, Any]:
        return self.request("POST", "/repos", json={"url": url})

    def reindex(self, repo_id: str) -> dict[str, Any]:
        return self.request("POST", f"/repos/{repo_id}/reindex")

    def job(self, job_id: str) -> dict[str, Any]:
        return self.request("GET", f"/jobs/{job_id}")

    def ask(
        self,
        repo_id: str,
        question: str,
        history: list[dict[str, str]] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.request("POST", "/ask", json=ask_payload(repo_id, question, history, filters))

    def ask_stream(
        self,
        repo_id: str,
        question: str,
        history: list[dict[str, str]] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        payload = ask_payload(repo_id, question, history, filters)
        try:
            with self.http.stream("POST", "/ask/stream", json=payload) as response:
                if response.status_code >= 400:
                    response.read()
                    raise BackendError(error_detail(response), response.status_code)
                for line in response.iter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.HTTPError as exc:
            raise BackendError(f"backend is not reachable ({type(exc).__name__})") from exc

    def stats(self) -> dict[str, Any]:
        return self.request("GET", "/stats")

    def scope(self, repo_id: str) -> dict[str, Any]:
        return self.request("GET", f"/repos/{repo_id}/scope")
