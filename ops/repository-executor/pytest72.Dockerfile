FROM python:3.10-slim

# The checked-out repository is never installed. Runtime imports /repo/src.
RUN python -m pip --isolated install --no-cache-dir \
    setuptools==65.5.1 pytest==7.2.2 pluggy==1.0.0 iniconfig==2.0.0 \
    packaging==23.2 attrs==23.2.0 exceptiongroup==1.2.2 tomli==2.0.1 \
    py==1.11.0 hypothesis==6.68.2 sortedcontainers==2.4.0 numpy==1.24.4
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HOME=/tmp PYTHONPATH=/repo/src
WORKDIR /repo
USER 65534:65534
