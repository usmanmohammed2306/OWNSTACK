"""Run a fixed four-call comparison inside the shared-budget worker, capture redacted JSON."""
import json
from pathlib import Path
import subprocess


def main():
    destination = Path("docs/evidence/live-model-comparison.json")
    if destination.exists():
        raise SystemExit("Existing evidence is preserved; do not rerun automatically")
    cases = json.loads(Path("evals/held_out_routes_2026_10_07.json").read_text())
    command = ["docker", "compose", "-f", "compose.full.yaml", "exec", "-T", "worker", "python", "-m",
               "ownstack.evaluate_live", "--confirmed-credit-only", "--cases-json", json.dumps(cases)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    # Never persist stderr or environments. The module outputs synthetic cases
    # and bounded metrics only; invalid output is not claimed as evidence.
    report = json.loads(result.stdout)
    report["frozen_cases"] = cases
    report["process_exit_code"] = result.returncode
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved {len(report['rows'])} redacted comparison rows to {destination}; exit {result.returncode}")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
