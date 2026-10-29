"""The login limiter must not rate-limit ordinary saved-session polling."""
from pathlib import Path

def test_login_rate_key_counts_only_post_and_keeps_general_api_limit():
    config=(Path(__file__).parents[1]/'web/nginx.conf').read_text()
    assert 'map $request_method $ownstack_login_key' in config
    assert 'default "";' in config and 'POST $binary_remote_addr;' in config
    assert 'limit_req_zone $ownstack_login_key zone=login_limit:10m rate=6r/m;' in config
    session=config.split('location = /v1/session {',1)[1].split('\n    }',1)[0]
    assert 'limit_req zone=login_limit burst=10 nodelay;' in session
    assert 'limit_req zone=api_limit burst=40 nodelay;' in session
