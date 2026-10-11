import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from streamlit.testing.v1 import AppTest

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from tests.fakes import FakeLLM, fake_embedder, fake_generator, make_settings

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


@contextmanager
def running_backend(data_dir: Path, **overrides: object) -> Iterator[str]:
    settings = make_settings(data_dir, demo_password=OWNER_PASSWORD, **overrides)
    container = Container(
        settings, embedder_factory=fake_embedder, generator_factory=fake_generator, llm_factory=lambda _: FakeLLM()
    )
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
def backend_url(tmp_path: Path) -> Iterator[str]:
    with running_backend(tmp_path / "data") as url:
        yield url


@pytest.fixture
def page(backend_url: str, repo_url: str, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("BACKEND_URL", backend_url)
    monkeypatch.setenv("SAMPLE_REPO_URL", repo_url)
    return AppTest.from_file(APP, default_timeout=60).run()


def button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def index(page: AppTest, url: str) -> AppTest:
    page.chat_input(key="repo_url").set_value(url).run()
    return page


def on_landing(page: AppTest) -> bool:
    return [item.key for item in page.chat_input] == ["repo_url"]


def test_landing_page_asks_for_a_repository_and_selects_nothing(page: AppTest) -> None:
    assert not page.exception
    assert len(page.query_params["v"]) == 32
    assert on_landing(page)
    assert "GitHub URL" in page.chat_input(key="repo_url").placeholder
    assert not any("Press Enter" in item.value for item in page.markdown)
    assert any("Repositories you index appear here" in item.value for item in page.sidebar.markdown)


def test_sample_button_indexes_the_sample_repository(page: AppTest) -> None:
    button(page, "No repository in mind? Try a sample repository").click().run()
    assert not page.exception
    assert not on_landing(page)
    assert any(item.label == "origin" for item in page.sidebar.button)


def test_visitor_indexes_a_repository_then_asks_about_it(page: AppTest, repo_url: str) -> None:
    index(page, repo_url)
    assert not page.exception
    assert not on_landing(page)
    assert any(item.label == "origin" for item in page.sidebar.button)
    page.button(key="example_0").click().run()
    assert not page.exception
    assistant = [message for message in page.chat_message if message.name == "assistant"]
    assert assistant and assistant[0].markdown[0].value.startswith("See ")
    citation = assistant[0].markdown[0].value.removeprefix("See ")
    assert any(expander.label == citation for expander in page.expander)
    assert any("confidence</span>" in item.value for item in assistant[0].markdown)


def test_new_repository_button_returns_to_the_landing_page(page: AppTest, repo_url: str) -> None:
    index(page, repo_url)
    button(page, "New repository").click().run()
    assert on_landing(page)


def test_owner_tools_are_hidden_unless_requested(page: AppTest, repo_url: str) -> None:
    index(page, repo_url)
    assert not any(item.key == "owner_password" for item in page.text_input)
    page.query_params["owner"] = "1"
    page.run()
    assert page.text_input(key="owner_password").label == "Owner password"


def test_suggested_questions_and_helpful_refusal(
    tmp_path: Path, repo_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running_backend(tmp_path / "strict", min_vector_score=0.99) as url:
        monkeypatch.setenv("BACKEND_URL", url)
        page = AppTest.from_file(APP, default_timeout=60).run()
        index(page, repo_url)
        labels = [item.label for item in page.button if (item.key or "").startswith("example_")]
        assert labels and "What does this repository do and how is it organized?" in labels
        page.chat_input[0].set_value("banana bread recipe").run()
        assistant = [message for message in page.chat_message if message.name == "assistant"][0]
        assert "couldn't find code" in assistant.markdown[0].value
        assert "Questions that work" not in assistant.markdown[0].value
        assert any((item.key or "").startswith("suggest_1_") for item in page.button)


def test_search_scope_controls_send_filters(page: AppTest, repo_url: str) -> None:
    index(page, repo_url)
    assert page.sidebar.selectbox(key="folder_origin").options == ["All folders", "app/ (2 files)", "web/ (1 files)"]
    page.sidebar.selectbox(key="folder_origin").set_value("web").run()
    page.chat_input[0].set_value("AuthService login").run()
    assistant = [message for message in page.chat_message if message.name == "assistant"][0]
    assert assistant.markdown[0].value.startswith("See web/index.ts")
