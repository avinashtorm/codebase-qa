from typing import Any

import httpx


class BackendError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BackendClient:
    def __init__(self, base_url: str, password: str = "", transport: httpx.BaseTransport | None = None) -> None:
        headers = {"X-Demo-Password": password} if password else {}
        self.http = httpx.Client(base_url=base_url, headers=headers, timeout=120.0, transport=transport)

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BackendError(f"backend is not reachable ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise BackendError(str(detail), response.status_code)
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

    def ask(self, repo_id: str, question: str) -> dict[str, Any]:
        return self.request("POST", "/ask", json={"repo_id": repo_id, "question": question})
