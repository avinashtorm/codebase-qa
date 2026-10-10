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
OWNER_PASSWORD = "test-owner-password"
RepoFactory = Callable[..., Path]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def backend_url(tmp_path: Path, make_repo: RepoFactory) -> Iterator[str]:
    settings = make_settings(tmp_path / "data", demo_password=OWNER_PASSWORD)
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)
    container.indexer.index(make_repo().as_uri())
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


@pytest.fixture
def page(backend_url: str, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("BACKEND_URL", backend_url)
    return AppTest.from_file(APP, default_timeout=30).run()


def button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def test_visitors_can_ask_without_any_password(page: AppTest) -> None:
    assert not page.exception
    assert page.sidebar.selectbox[0].value == "origin"
    assert len(page.chat_input) == 1
    assert [b.label for b in page.button if b.key and b.key.startswith("example_")]
    page.button(key="example_0").click().run()
    assert not page.exception
    assistant = [message for message in page.chat_message if message.name == "assistant"]
    assert assistant and "See app/auth.py" in assistant[0].markdown[0].value
    assert page.expander


def test_indexing_without_owner_password_shows_friendly_error(page: AppTest) -> None:
    page.text_input(key="index_url").input("https://github.com/fastapi/full-stack-fastapi-template").run()
    button(page, "Index repository").click().run()
    assert not page.exception
    assert any("owner password" in error.value for error in page.error)


def test_owner_password_field_is_shown_when_indexing_is_protected(page: AppTest) -> None:
    assert page.text_input(key="owner_password").label == "Owner password"
