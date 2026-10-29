"""The Alembic config layer must preserve percent signs in SQLAlchemy URLs."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_percent_url_survives_alembic_config_interpolation(tmp_path):
    path=tmp_path/'100%complete.sqlite'
    env=dict(os.environ,OWNSTACK_DATABASE_URL='sqlite:///'+str(path),OWNSTACK_AI_MODE='off',
             OWNSTACK_MAX_LIVE_CALLS='0',NEBIUS_API_KEY='',NEBIUS_MODEL_ID='',NEBIUS_PATCH_MODEL_ID='')
    result=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],
        cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr[-2000:]
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()==('e28f10d3a603',)
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
