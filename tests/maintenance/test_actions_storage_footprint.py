"""Read-only quota inventory pagination and fail-closed scope tests."""
import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "tools/actions_storage_footprint.py"
spec = importlib.util.spec_from_file_location("actions_storage_footprint", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_complete_paginated_inventory():
    calls = []

    def page(repository, number):
        calls.append((repository, number))
        start = (number - 1) * 100
        return {"total_count": 101,
                "artifacts": [{"id": i + 1, "size_in_bytes": 10}
                              for i in range(start, min(start + 100, 101))]}

    assert module.inventory("owner/repo", page) == (101, 1010)
    assert calls == [("owner/repo", 1), ("owner/repo", 2)]


@pytest.mark.parametrize("bad", [
    {"total_count": 2, "artifacts": [{"id": 1, "size_in_bytes": 5}]},
    {"total_count": 2, "artifacts": [{"id": 1, "size_in_bytes": 5},
                                       {"id": 1, "size_in_bytes": 5}]},
    {"total_count": 1, "artifacts": [{"id": 1, "size_in_bytes": -1}]},
    {"total_count": 1, "artifacts": "not a list"},
])
def test_incomplete_duplicate_or_invalid_inventory_is_not_reported(bad):
    with pytest.raises(ValueError):
        module.inventory("owner/repo", lambda _repo, _page: bad)


def test_one_unavailable_repo_never_reports_account_clearance(monkeypatch, capsys):
    monkeypatch.setattr(module, "github_page", lambda repo, page: (
        {"total_count": 0, "artifacts": []} if repo.endswith("forever-sim")
        else (_ for _ in ()).throw(OSError("access denied"))))
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "RETAINED_SCOPE=INCOMPLETE" in out
    assert "RETAINED_KNOWN_TWO_REPOS" not in out


def test_both_repos_report_retained_not_billing(monkeypatch, capsys):
    monkeypatch.setattr(module, "github_page", lambda repo, page: {
        "total_count": 1, "artifacts": [{"id": 1, "size_in_bytes": 512}]})
    assert module.main() == 0
    out = capsys.readouterr().out
    assert "RETAINED_KNOWN_TWO_REPOS bytes=1024" in out
    assert "BILLING_METER=UNKNOWN" in out


def test_inventory_rejects_total_count_changing_mid_scan():
    """An incomplete 101-of-102 page series must not authorize GC deletion."""
    def page(_repository, number):
        if number == 1:
            return {"total_count": 101, "artifacts": [
                {"id": i, "size_in_bytes": 10} for i in range(1, 101)]}
        return {"total_count": 102, "artifacts": [
            {"id": 101, "size_in_bytes": 10}]}

    with pytest.raises(ValueError, match="total_count changed"):
        module.verified_artifacts("owner/repo", page)


def test_deletion_workflow_uses_complete_verified_inventory():
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
                    encoding="utf-8")
    assert "from tools.actions_storage_footprint import verified_artifacts" in workflow
    assert "return verified_artifacts(repo, fetch_page)" in workflow
    assert workflow.index("return verified_artifacts(repo, fetch_page)") < workflow.index(
        "candidates = []")
