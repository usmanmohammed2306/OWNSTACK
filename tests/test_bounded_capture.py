"""Trusted tiny subprocesses only, never model-authored code on the host."""
import sys
from ownstack.bounded_process import capture


def test_normal_streams_complete_without_output_files():
    result=capture([sys.executable,'-c',"import sys;print('ok');sys.stderr.write('note')"],b'',timeout=3,limit=100)
    assert result['stdout_bytes']==b'ok\n' and result['stderr']=='note'
    assert result['exit_code']==0 and result['failure']==''


def test_output_flood_is_stopped_with_bounded_retention():
    result=capture([sys.executable,'-c',"import os\nwhile True: os.write(1,b'x'*65536)"],b'',timeout=3,limit=1024)
    assert result['failure']=='Candidate output limit exceeded'
    assert len(result['stdout_bytes'])<=1025 and result['exit_code']!=0


def test_local_deadline_kills_and_reaps_trusted_process():
    result=capture([sys.executable,'-c','import time;time.sleep(10)'],b'',timeout=.05,limit=100)
    assert result['failure']=='Local check deadline exceeded' and result['exit_code']!=0
