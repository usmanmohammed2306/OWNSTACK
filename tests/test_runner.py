from pathlib import Path
import pytest
from ownstack.patch_agent import fixture_patch
from ownstack.runner import materialize, trusted_local_verification, validate_patch


def test_fixture_patch_passes_independent_checks():
    result = trusted_local_verification(fixture_patch())
    assert result["passed"], result["stderr"]


def test_runner_rejects_path_and_anchor_escape(tmp_path):
    patch = fixture_patch()
    patch["edits"][0]["path"] = "../secrets.txt"
    with pytest.raises(ValueError):
        validate_patch(patch)
    patch = fixture_patch()
    patch["edits"][0]["old"] = "not present"
    with pytest.raises(ValueError):
        materialize(patch, tmp_path)


def test_runner_rejects_second_edit_and_oversized_source():
    patch = fixture_patch()
    patch["edits"].append(patch["edits"][0].copy())
    with pytest.raises(ValueError):
        validate_patch(patch)
    patch = fixture_patch()
    patch["edits"][0]["new"] = "x" * 12_001
    with pytest.raises(ValueError):
        validate_patch(patch)
