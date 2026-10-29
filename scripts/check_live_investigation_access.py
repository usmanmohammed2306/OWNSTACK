"""No-inference HTTP checks for the exact privately rehearsed Atlas grant."""
import json
import argparse
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-only", action="store_true", help="Read/isolation/proof only; never revoke")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    directory = root / ".private/ownstack-investigation-live-6d18k_5n"
    if not (directory / "authorization.json").is_file():
        raise SystemExit("Requires the retained approved private live fixture")
    report, clients = {"inference_calls": 0, "checks": []}, []
    def identity(user):
        client = httpx.Client(base_url="http://127.0.0.1:8097", headers={"Origin": "http://127.0.0.1:8097"}, timeout=15)
        auth = client.post("/v1/session", json={"username": user, "password": "demo-only-pass"})
        assert auth.status_code == 200
        client.headers["X-CSRF-Token"] = auth.json()["csrf_token"]
        clients.append(client)
        return client
    try:
        admin, contractor, nova = [identity(user) for user in ("atlas-admin", "atlas-contractor", "nova-admin")]
        def check(name, response, expected):
            assert response.status_code == expected, (name, response.status_code)
            report["checks"].append({"name": name, "status": expected})
        path = "/v1/host/projects/atlas-project/documents/atlas-live-doc"
        check("atlas-approved-read", contractor.get(path), 200)
        check("nova-cannot-read-atlas", nova.get(path), 404)
        check("atlas-cannot-read-nova", contractor.get("/v1/host/projects/nova-project/documents/nova-live-doc"), 404)
        if not args.read_only:
            grant = next(row for row in admin.get("/v1/variations").json() if row["project_id"] == "atlas-project" and row["state"] == "active")
            check("revoke-exact-synthetic-grant", admin.post(f'/v1/variations/{grant["id"]}/revoke', headers={"Idempotency-Key": "live-investigation-revoke"}), 200)
            check("atlas-read-denied-after-revoke", contractor.get(path), 403)
        request = next(row for row in admin.get("/v1/requests").json() if row["kind"] == "access")
        attempts = admin.get(f'/v1/requests/{request["id"]}/attempts').json()
        assert len(attempts) == 1 and attempts[0]["state"] == "accepted"
        report["accepted_attempt"] = attempts[0]
        proof = admin.get(f'/v1/requests/{request["id"]}/proof')
        check("tenant-private-proof", proof, 200)
        prefix = "access-readonly" if args.read_only else "access"
        (directory / (prefix + "-proof.json")).write_text(json.dumps(proof.json(), indent=2) + "\n")
        report["budget_after"] = admin.get('/v1/inference-budget').json()
        (directory / (prefix + "-http-result.json")).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"checks_passed": len(report["checks"]), "inference_calls": 0, "grant_state": "unchanged" if args.read_only else "revoked"}))
    finally:
        for client in clients:
            client.post('/v1/session/logout')
            client.close()


if __name__ == "__main__":
    main()
