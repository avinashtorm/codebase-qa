import html
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
MAX_TURN_CHARS = 1500
CONFIDENCE_LABELS = {"high": "High confidence", "medium": "Medium confidence", "low": "Low confidence"}
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
.badge {display: inline-block; border-radius: 999px; padding: 0.1rem 0.6rem; font-size: 0.75rem; font-weight: 600;
  margin: 0.2rem 0 0.4rem 0; cursor: help;}
.badge-high {background: rgba(46, 160, 67, 0.18); color: #3FB950; border: 1px solid rgba(63, 185, 80, 0.4);}
.badge-medium {background: rgba(187, 128, 9, 0.18); color: #D29922; border: 1px solid rgba(210, 153, 34, 0.4);}
.badge-low {background: rgba(248, 81, 73, 0.15); color: #F85149; border: 1px solid rgba(248, 81, 73, 0.4);}
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
    st.session_state["view"] = "chat"


def show_stats() -> None:
    st.session_state["view"] = "stats"


def stats_page() -> None:
    st.markdown('<div class="hero-title">Usage stats</div>', unsafe_allow_html=True)
    try:
        stats = client().stats()
    except BackendError as exc:
        st.error(str(exc))
        return
    st.markdown(
        f'<div class="hero-subtitle">All questions answered by this deployment. Cost is estimated at paid-tier '
        f'prices for {stats["model"]}; cached answers cost nothing.</div>',
        unsafe_allow_html=True,
    )
    first, second, third = st.columns(3)
    first.metric("Questions asked", stats["questions"])
    second.metric("Average latency", f'{stats["avg_latency_ms"] / 1000:.1f} s')
    third.metric("p95 latency", f'{stats["p95_latency_ms"] / 1000:.1f} s')
    fourth, fifth, sixth = st.columns(3)
    fourth.metric("Estimated total cost", f'${stats["total_cost_usd"]:.4f}')
    fifth.metric("Refusal rate", f'{stats["refusal_rate"] * 100:.0f}%')
    sixth.metric("LLM calls (cached)", f'{stats["llm_calls"]} ({stats["cached_calls"]})')
    if stats["avg_stage_ms"]:
        st.markdown('<div class="section-label">Average time per stage (ms)</div>', unsafe_allow_html=True)
        rows = [{"stage": stage, "ms": ms} for stage, ms in stats["avg_stage_ms"].items()]
        st.dataframe(rows, hide_index=True)


def repo_scope(repo_id: str) -> dict[str, Any]:
    cache: dict[str, Any] = st.session_state.setdefault("scopes", {})
    if repo_id not in cache:
        try:
            cache[repo_id] = client().scope(repo_id)
        except BackendError:
            return {"folders": {}, "languages": {}}
    return cache[repo_id]


def scope_controls(repo: dict[str, Any]) -> dict[str, Any]:
    scope = repo_scope(repo["repo_id"])
    st.markdown('<div class="section-label">Search scope</div>', unsafe_allow_html=True)
    folders = ["", *scope["folders"]]
    folder = st.selectbox(
        "Folder",
        folders,
        format_func=lambda name: "All folders" if not name else f"{name}/ ({scope['folders'][name]} files)",
        key=f"folder_{repo['repo_id']}",
    )
    languages = st.multiselect(
        "Languages",
        list(scope["languages"]),
        format_func=lambda name: f"{name} ({scope['languages'][name]})",
        placeholder="All languages",
        key=f"languages_{repo['repo_id']}",
    )
    return {"folder": folder, "languages": languages}


def sidebar(
    health: dict[str, Any], repos: list[dict[str, Any]], active: dict[str, Any] | None
) -> tuple[bool, dict[str, Any]]:
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
        filters = scope_controls(active) if active is not None else {"folder": "", "languages": []}
        st.markdown('<div class="section-label">Settings</div>', unsafe_allow_html=True)
        show_details = st.toggle("Show retrieval details", value=False)
        st.button("Usage stats", icon=":material/monitoring:", type="tertiary", on_click=show_stats)
        repos_per_day = health["index_per_visitor_per_day"]
        questions_per_day = health["ask_per_visitor_per_day"]
        hours = f'{health["repo_ttl_hours"]:.0f}'
        note = (
            f"Up to {repos_per_day} repositories and {questions_per_day} questions per day. Your repositories are "
            f"private to this link and are deleted {hours} hours after you last use them."
        )
        st.markdown(f'<div class="muted" style="margin-top:1.4rem">{note}</div>', unsafe_allow_html=True)
    return show_details, filters


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


def confidence_badge(response: dict[str, Any]) -> str:
    level = response.get("confidence")
    if level not in CONFIDENCE_LABELS or response.get("route") == "tool":
        return ""
    reasons = html.escape("; ".join(response.get("confidence_reasons", [])), quote=True)
    return f'<span class="badge badge-{level}" title="{reasons}">{CONFIDENCE_LABELS[level]}</span>'


def send_feedback(answer_id: str) -> None:
    value = st.session_state.get(f"feedback_{answer_id}")
    if value is None:
        return
    try:
        client().feedback(answer_id, "up" if value == 1 else "down")
        st.toast("Thanks for the feedback!")
    except BackendError as exc:
        st.toast(str(exc))


def feedback_buttons(response: dict[str, Any]) -> None:
    answer_id = response.get("answer_id")
    if answer_id:
        st.feedback("thumbs", key=f"feedback_{answer_id}", on_change=send_feedback, args=(answer_id,))


def render_assistant(message: dict[str, Any], repo: dict[str, Any], show_details: bool, key: str) -> None:
    response = message.get("response")
    if response and response.get("refused") and response.get("suggestions"):
        st.markdown(main_text(message["content"]))
        st.markdown('<div class="section-label">Try one of these instead</div>', unsafe_allow_html=True)
        question_buttons(response["suggestions"], key)
    else:
        st.markdown(message["content"])
    if response:
        badge = confidence_badge(response)
        if badge:
            st.markdown(badge, unsafe_allow_html=True)
        render_citations(response, repo)
        feedback_buttons(response)
        if show_details:
            render_details(response)


def example_buttons(repo: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">Suggested questions</div>', unsafe_allow_html=True)
    question_buttons(repo.get("suggested_questions") or list(GENERIC_EXAMPLES), "example")


def recent_turns(history: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    turns = [message for message in history if message.get("response") or message["role"] == "user"]
    return [
        {"role": message["role"], "content": main_text(message["content"])[:MAX_TURN_CHARS]}
        for message in turns[-limit:]
    ]


def stream_response(
    repo_id: str, question: str, previous: list[dict[str, str]], filters: dict[str, Any]
) -> dict[str, Any]:
    placeholder = st.empty()
    placeholder.markdown('<span class="muted">Searching the code...</span>', unsafe_allow_html=True)
    text = ""
    try:
        for event in client().ask_stream(repo_id, question, previous, filters):
            if event["type"] == "delta":
                text += event["text"]
                placeholder.markdown(text + " ▌")
            elif event["type"] == "error":
                raise BackendError(event["detail"])
            elif event["type"] == "final":
                return event["response"]
        raise BackendError("the answer stream ended unexpectedly")
    finally:
        placeholder.empty()


def chat(repo: dict[str, Any], show_details: bool, filters: dict[str, Any]) -> None:
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
    previous = recent_turns(history)
    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        try:
            response = stream_response(repo["repo_id"], question, previous, filters)
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
    show_details, filters = sidebar(health, repos, active)
    if st.session_state.get("view") == "stats":
        stats_page()
        return
    if active is None:
        landing()
        return
    owner_tools(active)
    repo_header(active)
    chat(active, show_details, filters)


main()
