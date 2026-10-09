from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request

from codebase_qa.api.schemas import AskRequest, AskResponse, IndexRepoRequest, RepoOut
from codebase_qa.config import get_settings
from codebase_qa.container import Container
from codebase_qa.generation.gemini_generator import GenerationError
from codebase_qa.ingestion.git import GitError


def get_container(request: Request) -> Container:
    return request.app.state.container


Services = Annotated[Container, Depends(get_container)]


def create_app(container: Container | None = None) -> FastAPI:
    app = FastAPI(title="Codebase Q&A", version="0.1.0")
    app.state.container = container or Container(get_settings())

    @app.post("/repos", response_model=RepoOut)
    def index_repo(body: IndexRepoRequest, services: Services) -> RepoOut:
        try:
            record = services.indexer.index(body.url)
        except GitError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RepoOut.from_record(record)

    @app.get("/repos", response_model=list[RepoOut])
    def list_repos(services: Services) -> list[RepoOut]:
        return [RepoOut.from_record(record) for record in services.repo_records()]

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, services: Services) -> AskResponse:
        record = services.repo_record(body.repo_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"repo {body.repo_id} is not indexed")
        try:
            result = services.pipeline(record).ask(body.question)
        except GenerationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return AskResponse.from_result(result)

    return app


app = create_app()
