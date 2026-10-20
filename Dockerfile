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
COPY docs/evidence/live-workflow.json docs/evidence/live-patch-super.json docs/evidence/manual-recovery.json docs/evidence/live-model-comparison.json docs/evidence/expiry-and-cap.json ./docs/evidence/
RUN python -m pip install --no-cache-dir -c constraints.txt . \
    && chmod -R a+rX /app \
    && groupadd --gid 10001 ownstack \
    && useradd --uid 10001 --gid 10001 --no-create-home ownstack

USER 10001:10001

CMD ["python", "-m", "uvicorn", "ownstack.api:app", "--host", "0.0.0.0", "--port", "8800"]
