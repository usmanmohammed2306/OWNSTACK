FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OWNSTACK_SOURCE_ROOT=/app
WORKDIR /app

COPY pyproject.toml constraints.txt README.md LICENSE ./
COPY src ./src
COPY sample_app ./sample_app
COPY checks ./checks
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY evals/real_issues_v1/cases.jsonl evals/real_issues_v1/manifest.json ./evals/real_issues_v1/
COPY evals/repository_additions_v2/cases.jsonl evals/repository_additions_v2/manifest.json ./evals/repository_additions_v2/
COPY evals/repository_candidates ./evals/repository_candidates
COPY ops/repository-executor ./ops/repository-executor
COPY docs/evidence/live-workflow.json docs/evidence/live-patch-super.json docs/evidence/manual-recovery.json docs/evidence/live-model-comparison.json docs/evidence/expiry-and-cap.json ./docs/evidence/
RUN python -m pip install --no-cache-dir -c constraints.txt . \
    && chmod -R a+rX /app \
    && groupadd --gid 10001 ownstack \
    && useradd --uid 10001 --gid 10001 --no-create-home ownstack

USER 10001:10001

CMD ["python", "-m", "uvicorn", "ownstack.api:app", "--host", "0.0.0.0", "--port", "8800"]
