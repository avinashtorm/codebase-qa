import os
import re
import time
import uuid
from typing import Any

import streamlit as st
from backend_client import BackendClient, BackendError
from code_view import citation_block, github_link, render_code

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
JOB_TIMEOUT_SECONDS = 900
VISITOR_ID = re.compile(r"^[0-9a-f]{32}$")
SAMPLE_REPO_URL = os.environ.get("SAMPLE_REPO_URL", "https://github.com/fastapi/full-stack-fastapi-template")
GENERIC_EXAMPLES = (
    "What does this repository do and how is it organized?",
    "Where is the application's entry point?",
    "How is configuration loaded?",
)
SUGGESTIONS_HEADING = "**Questions that work for this repository:**"
STYLE = """
<style>
.block-container {max-width: 920px; padding-top: 2.5rem;}
[data-testid="stSidebar"] .block-container {padding-top: 1.5rem;}
.app-brand {font-size: 1.15rem; font-weight: 700; letter-spacing: 0.2px; margin-bottom: 0.1rem;}
.app-tagline {color: #8B949E; font-size: 0.8rem; margin-bottom: 1.2rem;}
.section-label {color: #8B949E; font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.08em; margin: 1.4rem 0 0.4rem 0;}
.hero-title {font-size: 2.1rem; font-weight: 700; margin-bottom: 0.2rem;}
.hero-subtitle {color: #8B949E; font-size: 1.02rem; margin-bottom: 1.6rem;}
.feature {border: 1px solid #30363D; border-radius: 10px; padding: 0.9rem 1rem; min-height: 12rem;}
.feature b {display: block; margin-bottom: 0.25rem;}
.feature span {color: #8B949E; font-size: 0.86rem;}
.repo-title {font-size: 1.5rem; font-weight: 700; margin-bottom: 0;}
.repo-meta {color: #8B949E; font-size: 0.85rem; margin-bottom: 1rem;}
.muted {color: #8B949E; font-size: 0.8rem;}
</style>
"""

st.set_page_config(page_title="Codebase Q&A", page_icon=":material/manage_search:", layout="wide")


def visitor_ip() -> str:
    forwarded = st.context.headers.get("X-Forwarded-For")
    if isinstance(forwarded, str) and forwarded:
        return forwarded.split(",")[-1].strip()
    address = st.context.ip_address
    return address if isinstance(address, str) else ""


def visitor_id() -> str:
    current = st.query_params.get("v", "")
    if not VISITOR_ID.match(current):
        current = uuid.uuid4().hex
        st.query_params["v"] = current
    return current


def client() -> BackendClient:
    return BackendClient(
        BACKEND_URL,
        st.session_state.get("owner_password", ""),
        visitor_ip(),
        visitor_id=visitor_id(),
    )


def repo_name(repo: dict[str, Any]) -> str:
    match = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", repo["url"])
    return match.group(1) if match else repo["repo_id"]


def wait_for_job(job: dict[str, Any], label: str) -> dict[str, Any]:
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    with st.status(label, expanded=True) as status:
        while job["status"] in ("queued", "running") and time.monotonic() < deadline:
            status.update(label=f"{label}: {job['progress']}")
            time.sleep(1.5)
            job = client().job(job["job_id"])
        if job["status"] == "succeeded":
            status.update(label=f"{label}: done", state="complete", expanded=False)
        else:
            status.update(label=f"{label}: {job.get('error') or 'still running'}", state="error")
    return job


def select_repo(repo_id: str | None) -> None:
    st.session_state["active_repo"] = repo_id


def sidebar(health: dict[str, Any], repos: list[dict[str, Any]], active: dict[str, Any] | None) -> bool:
    with st.sidebar:
        st.markdown('<div class="app-brand">Codebase Q&A</div>', unsafe_allow_html=True)
        st.markdown('<div class="app-tagline">Cited answers about any GitHub repository</div>', unsafe_allow_html=True)
        st.button(
            "New repository",
            icon=":material/add:",
            type="primary" if active is None else "secondary",
            use_container_width=True,
            on_click=select_repo,
            args=(None,),
        )
        st.markdown('<div class="section-label">Your repositories</div>', unsafe_allow_html=True)
        if not repos:
            st.markdown('<div class="muted">Repositories you index appear here.</div>', unsafe_allow_html=True)
        for repo in repos:
            is_active = active is not None and repo["repo_id"] == active["repo_id"]
            st.button(
                repo_name(repo),
                key=f"repo_{repo['repo_id']}",
                icon=":material/folder_open:" if is_active else ":material/folder:",
                type="secondary" if is_active else "tertiary",
                use_container_width=True,
                on_click=select_repo,
                args=(repo["repo_id"],),
            )
        st.markdown('<div class="section-label">Settings</div>', unsafe_allow_html=True)
        show_details = st.toggle("Show retrieval details", value=False)
        repos_per_day = health["index_per_visitor_per_day"]
        questions_per_day = health["ask_per_visitor_per_day"]
        hours = f'{health["repo_ttl_hours"]:.0f}'
        note = (
            f"Up to {repos_per_day} repositories and {questions_per_day} questions per day. Your repositories are "
            f"private to this link and are deleted {hours} hours after you last use them."
        )
        st.markdown(f'<div class="muted" style="margin-top:1.4rem">{note}</div>', unsafe_allow_html=True)
    return show_details


def feature(title: str, text: str) -> str:
    return f'<div class="feature"><b>{title}</b><span>{text}</span></div>'


def landing() -> None:
    st.markdown('<div class="hero-title">Ask questions about any codebase</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hero-subtitle">Paste a public GitHub repository. It is indexed in a few minutes, then every '
        "answer cites the exact files and line ranges it comes from.</div>",
        unsafe_allow_html=True,
    )
    with st.container():
        url = st.chat_input("Paste a public GitHub URL, e.g. https://github.com/owner/repository", key="repo_url")
    sample = st.button("No repository in mind? Try a sample repository", type="tertiary")
    if url:
        index_repository(url.strip())
    elif sample:
        index_repository(SAMPLE_REPO_URL)
    st.write("")
    columns = st.columns(3)
    features = [
        ("Exact citations", "Every claim links to path:start-end, checked against the retrieved code."),
        ("Code-aware search", "Functions and classes are indexed whole, not cut at random lines."),
        ("Private by default", "Only you see your repositories; they are removed after 24 idle hours."),
    ]
    for column, (title, text) in zip(columns, features, strict=True):
        column.markdown(feature(title, text), unsafe_allow_html=True)


def index_repository(url: str) -> None:
    if not url:
        st.warning("Paste a GitHub repository URL first, for example https://github.com/owner/repository.")
        return
    try:
        job = wait_for_job(client().index(url), "Indexing repository")
    except BackendError as exc:
        st.error(str(exc))
        return
    if job["status"] == "succeeded":
        select_repo(job["result"]["repo_id"])
        st.rerun()


def owner_tools(active: dict[str, Any]) -> None:
    if st.query_params.get("owner") != "1":
        return
    with st.sidebar.expander("Owner tools", icon=":material/admin_panel_settings:"):
        st.text_input("Owner password", type="password", key="owner_password")
        if st.button("Re-index this repository", use_container_width=True):
            try:
                job = wait_for_job(client().reindex(active["repo_id"]), "Re-indexing")
                if job["status"] == "succeeded":
                    report = job["result"]
                    st.success(
                        f"{report['method']}: {report['files_changed']} files changed, "
                        f"+{report['chunks_added']} / -{report['chunks_removed']} chunks in {report['seconds']:.1f}s"
                    )
            except BackendError as exc:
                st.error("Wrong or missing owner password." if exc.status_code == 401 else str(exc))


def repo_header(repo: dict[str, Any]) -> None:
    st.markdown(f'<div class="repo-title">{repo_name(repo)}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="repo-meta"><a href="{repo["url"]}" target="_blank">GitHub</a> &middot; commit '
        f'<code>{repo["commit_sha"][:7]}</code> &middot; {repo["file_count"]} files &middot; '
        f'{repo["chunk_count"]} code chunks</div>',
        unsafe_allow_html=True,
    )


def render_citations(response: dict[str, Any], repo: dict[str, Any]) -> None:
    for citation in response["citations"]:
        title = f"{citation['path']}:{citation['start_line']}-{citation['end_line']}"
        with st.expander(title, icon=":material/code:"):
            block = citation_block(citation, response["context"])
            st.html(render_code(block, citation["language"], citation["path"]))
            link = github_link(
                repo["url"], response["commit_sha"], citation["path"], citation["start_line"], citation["end_line"]
            )
            st.markdown(f"[View on GitHub at `{response['commit_sha'][:7]}`]({link})")


def render_details(response: dict[str, Any]) -> None:
    with st.expander("Retrieval details", icon=":material/query_stats:"):
        st.markdown("**Per-stage latency (ms)**")
        st.dataframe([{"stage": stage, "ms": ms} for stage, ms in response["timings_ms"].items()], hide_index=True)
        st.markdown("**Retrieved chunks**")
        rows = [
            {"rank": rank, "location": f"{c['path']}:{c['start_line']}-{c['end_line']}", "score": round(c["score"], 4)}
            | {name: round(value, 4) for name, value in c["scores"].items()}
            for rank, c in enumerate(response["context"], start=1)
        ]
        st.dataframe(rows, hide_index=True)
        st.caption(f"LLM called: {response['used_llm']} | invalid citations dropped: {response['invalid_citations']}")


def main_text(answer: str) -> str:
    return answer.split("\n\n" + SUGGESTIONS_HEADING, 1)[0]


def question_buttons(questions: list[str], key: str) -> None:
    for number, question in enumerate(questions):
        if st.button(question, key=f"{key}_{number}", icon=":material/arrow_forward:"):
            st.session_state["pending_question"] = question
            st.rerun()


def render_assistant(message: dict[str, Any], repo: dict[str, Any], show_details: bool, key: str) -> None:
    response = message.get("response")
    if response and response.get("refused") and response.get("suggestions"):
        st.markdown(main_text(message["content"]))
        st.markdown('<div class="section-label">Try one of these instead</div>', unsafe_allow_html=True)
        question_buttons(response["suggestions"], key)
    else:
        st.markdown(message["content"])
    if response:
        render_citations(response, repo)
        if show_details:
            render_details(response)


def example_buttons(repo: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">Suggested questions</div>', unsafe_allow_html=True)
    question_buttons(repo.get("suggested_questions") or list(GENERIC_EXAMPLES), "example")


def chat(repo: dict[str, Any], show_details: bool) -> None:
    history: list[dict[str, Any]] = st.session_state.setdefault("history", {}).setdefault(repo["repo_id"], [])
    for position, message in enumerate(history):
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_assistant(message, repo, show_details, f"suggest_{position}")
            else:
                st.markdown(message["content"])
    typed = st.chat_input(f"Ask a question about {repo_name(repo)}")
    question = typed or st.session_state.pop("pending_question", None)
    if not question:
        if not history:
            example_buttons(repo)
        return
    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching the code..."):
                response = client().ask(repo["repo_id"], question)
            message = {"role": "assistant", "content": response["answer"], "response": response}
        except BackendError as exc:
            message = {"role": "assistant", "content": f"Sorry, that didn't work: {exc}"}
        history.append(message)
        render_assistant(message, repo, show_details, f"suggest_{len(history) - 1}")


def main() -> None:
    st.markdown(STYLE, unsafe_allow_html=True)
    try:
        health = client().health()
        repos = client().repos()
    except BackendError as exc:
        st.error(f"Cannot reach the backend at {BACKEND_URL}: {exc}")
        return
    by_id = {repo["repo_id"]: repo for repo in repos}
    active = by_id.get(st.session_state.get("active_repo") or "")
    show_details = sidebar(health, repos, active)
    if active is None:
        landing()
        return
    owner_tools(active)
    repo_header(active)
    chat(active, show_details)


main()
