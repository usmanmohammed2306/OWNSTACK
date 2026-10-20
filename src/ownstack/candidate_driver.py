"""Fixed candidate protocol. This is not the oracle and cannot issue a verdict."""

from pathlib import Path

SANDBOX_SOURCE = Path(__file__).with_name('candidate_sandbox.py').read_text()
DRIVER = SANDBOX_SOURCE + r'''
import base64, json, sys
payload = json.load(sys.stdin)
# This flag is set only by the host helper after exact known-fixture comparison.
# API/queue candidate_payload never accepts or supplies it. No fallback on failure.
if payload.get("trusted_local_fixture") is not True:
    lockdown()
namespace = {"__name__": "candidate"}
exec(compile(payload["source"], "candidate.py", "exec"), namespace)
outputs = []
for case in payload["cases"]:
    result = namespace["export_pdf"](case["project"], list(case["rows"]))
    if type(result) is not bytes or len(result) > 65536:
        raise ValueError("Expected bounded PDF bytes")
    outputs.append(base64.b64encode(result).decode("ascii"))
sys.stdout.write(json.dumps(outputs))
'''
