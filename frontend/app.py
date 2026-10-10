import os
import time
from typing import Any

import streamlit as st
from backend_client import BackendClient, BackendError
from code_view import citation_block, github_link, render_code

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
JOB_TIMEOUT_SECONDS = 900

st.set_page_config(page_title="Codebase Q&A", page_icon=":mag:", layout="wide")


def visitor_ip() -> str:
    forwarded = st.context.headers.get("X-Forwarded-For")
    if isinstance(forwarded, str) and forwarded:
        return forwarded.split(",")[-1].strip()
    address = st.context.ip_address
    return address if isinstance(address, str) else ""


def client() -> BackendClient:
    return BackendClient(BACKEND_URL, st.session_state.get("demo_password", ""), visitor_ip())


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


def password_gate(health: dict[str, Any]) -> bool:
    if not health["password_required"] or st.session_state.get("password_ok"):
        return True
    with st.sidebar.form("password_form"):
        password = st.text_input("Demo password", type="password")
        submitted = st.form_submit_button("Unlock")
    if submitted:
        st.session_state["demo_password"] = password
        try:
            client().repos()
            st.session_state["password_ok"] = True
            st.rerun()
        except BackendError:
            st.sidebar.error("Wrong password.")
    st.info("This demo is password protected. Enter the password in the sidebar.")
    return False


def index_section() -> None:
    st.sidebar.subheader("Index a repository")
    url = st.sidebar.text_input("GitHub URL", placeholder="https://github.com/owner/repo")
    if st.sidebar.button("Index", use_container_width=True, disabled=not url):
        try:
            job = wait_for_job(client().index(url.strip()), "Indexing")
            if job["status"] == "succeeded":
                st.session_state["selected_repo"] = job["result"]["repo_id"]
                st.rerun()
        except BackendError as exc:
            st.sidebar.error(str(exc))


def repo_picker(repos: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not repos:
        st.sidebar.info("No repositories indexed yet.")
        return None
    ids = [repo["repo_id"] for repo in repos]
    shas = {repo["repo_id"]: repo["commit_sha"][:7] for repo in repos}
    preferred = st.session_state.get("selected_repo")
    index = ids.index(preferred) if preferred in ids else 0
    chosen = st.sidebar.selectbox(
        "Repository",
        ids,
        index=index,
        format_func=lambda repo_id: f"{repo_id} @ {shas[repo_id]}",
    )
    st.session_state["selected_repo"] = chosen
    return next(repo for repo in repos if repo["repo_id"] == chosen)


def reindex_section(repo: dict[str, Any]) -> None:
    st.sidebar.caption(f"{repo['file_count']} files, {repo['chunk_count']} chunks, indexed {repo['indexed_at']}")
    if st.sidebar.button("Re-index (pull latest)", use_container_width=True):
        try:
            job = wait_for_job(client().reindex(repo["repo_id"]), "Re-indexing")
            if job["status"] == "succeeded":
                st.session_state["reindex_report"] = job["result"]
                st.rerun()
        except BackendError as exc:
            st.sidebar.error(str(exc))
    report = st.session_state.get("reindex_report")
    if report and report["repo_id"] == repo["repo_id"]:
        st.sidebar.success(
            f"{report['method']}: {report['files_changed']} files changed, "
            f"+{report['chunks_added']} / -{report['chunks_removed']} chunks in {report['seconds']:.1f}s "
            f"({report['old_sha'][:7]} -> {report['new_sha'][:7]})"
        )


def render_citations(response: dict[str, Any], repo: dict[str, Any]) -> None:
    for citation in response["citations"]:
        title = f"{citation['path']}:{citation['start_line']}-{citation['end_line']}"
        with st.expander(title):
            block = citation_block(citation, response["context"])
            st.html(render_code(block, citation["language"], citation["path"]))
            link = github_link(
                repo["url"], response["commit_sha"], citation["path"], citation["start_line"], citation["end_line"]
            )
            st.markdown(f"[View on GitHub at `{response['commit_sha'][:7]}`]({link})")


def render_details(response: dict[str, Any]) -> None:
    with st.expander("Retrieval details"):
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


def render_assistant(message: dict[str, Any], repo: dict[str, Any], show_details: bool) -> None:
    response = message.get("response")
    st.markdown(message["content"])
    if response:
        render_citations(response, repo)
        if show_details:
            render_details(response)


def chat(repo: dict[str, Any], show_details: bool) -> None:
    history: list[dict[str, Any]] = st.session_state.setdefault("history", {}).setdefault(repo["repo_id"], [])
    for message in history:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_assistant(message, repo, show_details)
            else:
                st.markdown(message["content"])
    question = st.chat_input(f"Ask about {repo['repo_id']}")
    if not question:
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
            message = {"role": "assistant", "content": f"Error: {exc}"}
        history.append(message)
        render_assistant(message, repo, show_details)


def main() -> None:
    st.title("Codebase Q&A")
    st.caption("Ask questions about a GitHub repository. Answers cite exact files and line ranges.")
    try:
        health = client().health()
    except BackendError as exc:
        st.error(f"Cannot reach the backend at {BACKEND_URL}: {exc}")
        return
    if not password_gate(health):
        return
    index_section()
    try:
        repos = client().repos()
    except BackendError as exc:
        st.error(str(exc))
        return
    repo = repo_picker(repos)
    show_details = st.sidebar.toggle("Show retrieval details", value=False)
    if repo is None:
        st.info("Index a repository from the sidebar to start asking questions.")
        return
    reindex_section(repo)
    chat(repo, show_details)


main()
