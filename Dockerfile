FROM python:3.11-slim

ARG TORCH_VERSION=2.14.1
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ARG RERANKER_MODEL=BAAI/bge-reranker-base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/models \
    TOKENIZERS_PARALLELISM=false \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    RERANKER_MODEL=${RERANKER_MODEL} \
    DATA_DIR=/app/data \
    TRUST_PROXY=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 user

WORKDIR /app

RUN pip install "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml ./
COPY backend ./backend
RUN pip install ".[frontend]"

RUN python -c "from sentence_transformers import CrossEncoder, SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}'); CrossEncoder('${RERANKER_MODEL}')" \
    && python -c "from tree_sitter_language_pack import get_parser; from codebase_qa.chunking.treesitter.languages import SUPPORTED_GRAMMARS; [get_parser(name) for name in SUPPORTED_GRAMMARS]" \
    && mkdir -p /app/data \
    && chown -R user:user /opt/models /app/data

COPY frontend ./frontend

ENV HF_HUB_OFFLINE=1
USER user
EXPOSE 8000 7860
CMD ["uvicorn", "codebase_qa.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
