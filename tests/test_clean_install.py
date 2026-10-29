"""Installed-package imports must use the explicit read-only source witness."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_installed_api_uses_explicit_source_root(tmp_path):
    root=Path(__file__).resolve().parents[1]
    site=tmp_path/'site';site.mkdir()
    shutil.copytree(root/'src/ownstack',site/'ownstack',ignore=shutil.ignore_patterns('__pycache__'))
    env=dict(os.environ,PYTHONPATH=str(site),OWNSTACK_SOURCE_ROOT=str(root),OWNSTACK_AI_MODE='off',
        OWNSTACK_MAX_LIVE_CALLS='0',NEBIUS_API_KEY='',OWNSTACK_DATABASE_URL='sqlite:///:memory:')
    result=subprocess.run([sys.executable,'-c',
        'from ownstack.api import app; from ownstack.repository_cockpit import catalog; '
        'assert len(catalog()) == 7; print("installed-import-ok")'],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert 'installed-import-ok' in result.stdout
