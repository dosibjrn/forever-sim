"""Fail-closed origin classification for unmerged PR artifact retention."""
import pytest

from tools.actions_artifact_pins import unmerged_pr_branch_refs


@pytest.mark.parametrize("label", [None, "", "deleted", "dosibjrn", 42])
def test_redacted_unmerged_pr_without_identifiable_origin_aborts_gc(label):
    """A missing owner cannot be assumed to identify an external fork."""
    with pytest.raises(ValueError, match="trustworthy head origin"):
        unmerged_pr_branch_refs([
            {"state": "closed", "merged_at": None,
             "head": {"ref": "clean/deleted", "repo": None, "label": label}},
        ], "dosibjrn/forever-sim")


def test_explicit_foreign_origin_and_known_deleted_local_origin_are_distinct():
    branches = unmerged_pr_branch_refs([
        {"state": "closed", "merged_at": None,
         "head": {"ref": "other-branch", "repo": None,
                  "label": "other-owner:other-branch"}},
        {"state": "closed", "merged_at": None,
         "head": {"ref": "work/old-native", "repo": None,
                  "label": "dosibjrn:work/old-native"}},
        {"state": "closed", "merged_at": "2026-11-10T00:00:00Z",
         "head": {"ref": "merged", "repo": None, "label": None}},
    ], "dosibjrn/forever-sim")
    assert branches == {"work/old-native"}


def test_unknown_deleted_branch_stops_before_any_next_pr_is_classified():
    """No best-effort partial protected set can authorize a GC deletion."""
    with pytest.raises(ValueError, match="trustworthy head origin"):
        unmerged_pr_branch_refs([
            {"merged_at": None,
             "head": {"ref": "work/known", "repo": None,
                      "label": "dosibjrn:work/known"}},
            {"merged_at": None,
             "head": {"ref": "work/unknown", "repo": None, "label": None}},
        ], "dosibjrn/forever-sim")
