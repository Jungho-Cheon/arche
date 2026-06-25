# syntax=docker/dockerfile:1.7
# WHY uv 베이스 이미지: workspace 동기화 + lockfile reproducibility 를 그대로
# 이미지에 옮기는 가장 단순한 경로.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:/root/.local/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /workspace

# 워크스페이스 매니페스트 / 락 먼저 복사 — layer 캐시 활용.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/README.md ./apps/api/
COPY eval/pyproject.toml eval/README.md ./eval/

# 소스 카피.
COPY apps/api/src ./apps/api/src
COPY eval/src ./eval/src

RUN uv sync --frozen --package arche-api --no-dev

EXPOSE 8000

CMD ["uv", "run", "--package", "arche-api", "uvicorn", "arche_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
