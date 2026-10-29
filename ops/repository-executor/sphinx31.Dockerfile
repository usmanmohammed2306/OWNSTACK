FROM python:3.8.2-slim

# Trusted registry dependencies only; source and candidates are mounted later.
RUN python -m pip --isolated install --no-cache-dir \
    setuptools==65.5.1 Sphinx==3.1.2 docutils==0.16 Jinja2==2.11.3 MarkupSafe==2.0.1 \
    Pygments==2.7.4 Babel==2.9.1 pytz==2023.3 snowballstemmer==2.2.0 \
    alabaster==0.7.13 imagesize==1.4.1 requests==2.31.0 \
    urllib3==1.26.18 certifi==2023.11.17 charset-normalizer==3.3.2 idna==3.6 \
    sphinxcontrib-applehelp==1.0.2 sphinxcontrib-devhelp==1.0.2 \
    sphinxcontrib-htmlhelp==1.0.3 sphinxcontrib-jsmath==1.0.1 \
    sphinxcontrib-qthelp==1.0.3 sphinxcontrib-serializinghtml==1.1.4 \
    pytest==6.2.5 pluggy==1.3.0 iniconfig==2.0.0 packaging==23.2 \
    attrs==23.2.0 py==1.11.0 toml==0.10.2
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HOME=/tmp PYTHONPATH=/repo
WORKDIR /repo
USER 65534:65534
