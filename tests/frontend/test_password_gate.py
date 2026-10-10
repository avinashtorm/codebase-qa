import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import uvicorn
from streamlit.testing.v1 import AppTest

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from tests.fakes import fake_embedder, fake_generator, make_settings

APP = str(Path(__file__).resolve().parents[2] / "frontend" / "app.py")
PASSWORD = "test-gate-password"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def backend_url(tmp_path: Path) -> Iterator[str]:
    settings = make_settings(tmp_path / "data", demo_password=PASSWORD)
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(container), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def unlock(app: AppTest, password: str) -> AppTest:
    app.sidebar.text_input[0].input(password)
    app.sidebar.button[0].click()
    return app.run()


@pytest.fixture
def app(backend_url: str, monkeypatch: pytest.MonkeyPatch) -> Callable[[], AppTest]:
    monkeypatch.setenv("BACKEND_URL", backend_url)
    return lambda: AppTest.from_file(APP, default_timeout=30).run()


def test_password_gate_rejects_wrong_password(app: Callable[[], AppTest]) -> None:
    page = app()
    assert not page.exception
    assert any("password protected" in info.value for info in page.info)
    page = unlock(page, "wrong")
    assert not page.exception
    assert any("Wrong password" in error.value for error in page.sidebar.error)


def test_password_gate_unlocks_with_correct_password(app: Callable[[], AppTest]) -> None:
    page = unlock(app(), PASSWORD)
    assert not page.exception
    assert page.session_state["password_ok"] is True
    assert any("Index a repository" in info.value for info in page.info)
