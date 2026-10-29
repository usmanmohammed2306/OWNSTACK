"""Exercise the local portal deep link, not just its generated bundle."""
import importlib.util
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_declared_customer_portal_deep_link_serves_shell_and_unknown_api_stays_404(tmp_path):
    spec=importlib.util.spec_from_file_location('customer_web_mount',Path(__file__).resolve().parents[1]/'scripts/customer_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    (tmp_path/'index.html').write_text('<html><main>Customer workspace</main></html>')
    app=FastAPI();module.mount_lab_web(app,tmp_path)
    with TestClient(app) as c:
        for path in ('/','/customer'):
            r=c.get(path);assert r.status_code==200 and 'Customer workspace' in r.text
        assert c.get('/v1/not-an-api').status_code==404
        assert c.get('/customer/../.env').status_code==404
