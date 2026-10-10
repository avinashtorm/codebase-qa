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
def repo_url(make_repo: RepoFactory) -> str:
    return make_repo().as_uri()


@pytest.fixture
def backend_url(tmp_path: Path, repo_url: str) -> Iterator[str]:
    settings = make_settings(tmp_path / "data", demo_password=OWNER_PASSWORD)
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


@pytest.fixture
def page(backend_url: str, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("BACKEND_URL", backend_url)
    return AppTest.from_file(APP, default_timeout=60).run()


def button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def index(page: AppTest, url: str) -> AppTest:
    page.text_input(key="repo_url").input(url)
    button(page, "Index repository").click().run()
    return page


def test_landing_page_asks_for_a_repository_and_selects_nothing(page: AppTest) -> None:
    assert not page.exception
    assert len(page.query_params["v"]) == 32
    assert page.text_input(key="repo_url").value == ""
    assert not page.chat_input
    assert any("Repositories you index appear here" in item.value for item in page.sidebar.markdown)


def test_sample_button_only_fills_the_url(page: AppTest) -> None:
    button(page, "No repository in mind? Use a sample repository").click().run()
    assert page.text_input(key="repo_url").value == "https://github.com/fastapi/full-stack-fastapi-template"
    assert not page.chat_input


def test_visitor_indexes_a_repository_then_asks_about_it(page: AppTest, repo_url: str) -> None:
    index(page, repo_url)
    assert not page.exception
    assert len(page.chat_input) == 1
    assert any(item.label == "origin" for item in page.sidebar.button)
    page.button(key="example_0").click().run()
    assert not page.exception
    assistant = [message for message in page.chat_message if message.name == "assistant"]
    assert assistant and "See app/auth.py" in assistant[0].markdown[0].value
    assert page.expander


def test_new_repository_button_returns_to_the_landing_page(page: AppTest, repo_url: str) -> None:
    index(page, repo_url)
    button(page, "New repository").click().run()
    assert not page.chat_input
    assert page.text_input(key="repo_url") is not None


def test_owner_tools_are_hidden_unless_requested(page: AppTest, repo_url: str) -> None:
    index(page, repo_url)
    assert not any(item.key == "owner_password" for item in page.text_input)
    page.query_params["owner"] = "1"
    page.run()
    assert page.text_input(key="owner_password").label == "Owner password"
