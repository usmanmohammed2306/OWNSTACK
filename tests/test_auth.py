import pytest
from fastapi import HTTPException
from ownstack.auth import parse_token


@pytest.mark.parametrize("token", ["", "not-a-token", "@@@@.deadbeef", "a" * 4097])
def test_malformed_tokens_fail_closed(token):
    with pytest.raises(HTTPException) as error:
        parse_token(token, "local-demo-secret-not-for-deployment")
    assert error.value.status_code == 401
