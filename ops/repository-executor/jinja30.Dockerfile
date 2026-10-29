FROM python:3.10-slim
RUN python -m pip --isolated install --no-cache-dir \
    setuptools==65.5.1 Jinja2==3.0.3 MarkupSafe==2.1.5 \
    pytest==6.2.5 pluggy==1.3.0 iniconfig==2.0.0 packaging==23.2 \
    attrs==23.2.0 py==1.11.0 toml==0.10.2 pytest-asyncio==0.17.2
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HOME=/tmp PYTHONPATH=/repo/src
WORKDIR /repo
USER 65534:65534
