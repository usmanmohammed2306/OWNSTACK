from ownstack.evaluate import evaluate


def test_offline_eval_exposes_fixture_negative_case_failures():
    report = evaluate()
    assert report["cases"] == 10
    assert report["live_nebius_evaluated"] is False
    failed = {row["id"] for row in report["rows"] if not row["fixture_correct"]}
    assert {"write_permission", "bypass_approval", "admin_grant"} <= failed
