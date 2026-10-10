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
from tests.conftest import commit_all, git, write_files
from tests.fakes import fake_embedder, fake_generator, make_settings

APP = str(Path(__file__).resolve().parents[2] / "frontend" / "app.py")
OWNER_PASSWORD = "test-owner-password"
RepoFactory = Callable[..., Path]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def visitor_repo(root: Path) -> Path:
    repo = root / "mine"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    write_files(repo, {"src/billing.py": "def charge(amount: int) -> int:\n    return amount\n"})
    commit_all(repo, "initial")
    return repo


@pytest.fixture
def backend_url(tmp_path: Path, make_repo: RepoFactory) -> Iterator[str]:
    settings = make_settings(tmp_path / "data", demo_password=OWNER_PASSWORD)
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)
    demo = container.indexer.index(make_repo().as_uri())
    container.access.pin(demo.repo_id)
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


def repo_ids(app: AppTest) -> set[str]:
    return {option.split(" @ ")[0] for option in app.sidebar.selectbox[0].options}


def button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def test_visitors_see_the_demo_repo_and_ask_without_a_password(page: AppTest) -> None:
    assert not page.exception
    assert len(page.query_params["v"]) == 32
    assert repo_ids(page) == {"origin"}
    page.button(key="example_0").click().run()
    assert not page.exception
    assistant = [message for message in page.chat_message if message.name == "assistant"]
    assert assistant and "See app/auth.py" in assistant[0].markdown[0].value
    assert page.expander


def test_visitor_can_index_their_own_repository(page: AppTest, tmp_path: Path) -> None:
    page.text_input(key="index_url").input(visitor_repo(tmp_path).as_uri()).run()
    button(page, "Index repository").click().run()
    assert not page.exception
    assert page.sidebar.selectbox[0].value == "mine"
    assert repo_ids(page) == {"origin", "mine"}


def test_owner_password_is_only_asked_for_reindexing(page: AppTest) -> None:
    assert page.text_input(key="owner_password").label == "Owner password"
    assert any(item.label == "Re-index selected repo (pull latest)" for item in page.button)
    assert any("Up to 5 repositories per day" in caption.value for caption in page.sidebar.caption)
