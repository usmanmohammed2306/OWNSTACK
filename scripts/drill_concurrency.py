"""Exercise simultaneous HTTP requests against the synthetic PostgreSQL stack."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from urllib.request import Request
from uuid import uuid4
from smoke_full_stack import BASE, call, login


def main():
    admin = login("atlas-admin")
    mode = call("GET", "/v1/inference-budget", admin)["mode"]
    if mode != "fixture":
        raise SystemExit("This drill requires fixture mode and will not consume live credits.")
    key = uuid4().hex
    body = {"text": "Give atlas-contractor read-only access to Project Atlas until Friday",
            "kind": "access", "project_id": "atlas-project", "viewer_id": "atlas-contractor",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}
    def create(_):
        request = Request(BASE + "/v1/requests", data=json.dumps(body).encode(), method="POST",
                          headers={"Content-Type": "application/json", "Origin": BASE,
                                   "X-CSRF-Token": admin.csrf, "Idempotency-Key": key})
        with admin.opener.open(request, timeout=15) as response:
            return json.load(response)["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(create, range(4)))
        assert len(set(ids)) == 1, "Duplicate requests created separate records"
        request_id = ids[0]
        results = list(pool.map(lambda _: call("POST", f"/v1/requests/{request_id}/interpret", admin,
                                               expected=202), range(4)))
        assert len({row["attempt_id"] for row in results}) == 1, "Duplicate model work launched"
    attempts = call("GET", f"/v1/requests/{request_id}/attempts", admin)
    assert len(attempts) == 1
    call("POST", "/v1/session/logout", admin)
    print(json.dumps({"concurrent_creates": 4, "unique_request": 1,
                      "concurrent_interpretations": 4, "unique_attempt": 1, "live_calls": 0}))


if __name__ == "__main__":
    main()
