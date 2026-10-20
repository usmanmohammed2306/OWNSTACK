"""Read an existing saved workflow across restarts with AI off. Never starts inference."""
import argparse
import json
from smoke_full_stack import call, login
from ownstack.proof import verify_envelope, saved_state_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id")
    parser.add_argument("--expected-digest")
    args = parser.parse_args()
    admin = login("atlas-admin")
    before = call("GET", "/v1/inference-budget", admin)
    assert before["mode"] == "off", "This rehearsal requires AI-off mode"
    request = call("GET", f"/v1/requests/{args.request_id}", admin)
    attempts = call("GET", f"/v1/requests/{args.request_id}/attempts", admin)
    proof = call("GET", f"/v1/requests/{args.request_id}/proof", admin)
    assert verify_envelope(proof)
    # Export timestamps and current file inventory intentionally differ between exports/builds.
    fingerprint = saved_state_fingerprint(proof)
    if args.expected_digest:
        assert fingerprint == args.expected_digest, "Saved workflow changed after restart"
    after = call("GET", "/v1/inference-budget", admin)
    assert before["reserved_calls"] == after["reserved_calls"]
    call("POST", "/v1/session/logout", admin)
    print(json.dumps({"request_id": args.request_id, "saved_state_sha256": fingerprint,
                      "status": request["status"], "saved_attempts": len(attempts),
                      "ai_mode": before["mode"], "reserved_calls": after["reserved_calls"],
                      "proof_digest": "verified", "new_model_calls": 0}))


if __name__ == "__main__":
    main()
