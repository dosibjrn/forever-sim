"""Read-only quota inventory pagination and fail-closed scope tests."""
import importlib.util
import io
from pathlib import Path
import urllib.error

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
    monkeypatch.setattr(module, "github_owner_page", lambda _page: [
        {"full_name": repo, "private": False} for repo in module.REPOSITORIES])
    monkeypatch.setattr(module, "github_page", lambda repo, page: (
        {"total_count": 0, "artifacts": []} if repo.endswith("forever-sim")
        else (_ for _ in ()).throw(OSError("access denied"))))
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "RETAINED_SCOPE=INCOMPLETE" in out
    assert "RETAINED_KNOWN_TWO_REPOS" not in out


def test_both_repos_report_retained_not_billing(monkeypatch, capsys):
    monkeypatch.setattr(module, "github_owner_page", lambda _page: [
        {"full_name": repo, "private": False} for repo in module.REPOSITORIES])
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


def test_public_owner_discovery_pages_and_keeps_canonical_repos():
    calls = []
    def page(number):
        calls.append(number)
        if number == 1:
            return [{"full_name": f"dosibjrn/extra-{i}", "private": False}
                    for i in range(100)]
        return [{"full_name": "dosibjrn/last", "private": False}]

    found = module.discover_public_owner_repos(page)
    assert calls == [1, 2]
    assert len(found) == 103
    assert set(module.REPOSITORIES).issubset(found)
    assert "dosibjrn/last" in found


@pytest.mark.parametrize("page", [
    [{"full_name": "somebody/foreign", "private": False}],
    [{"full_name": "dosibjrn/private", "private": True}],
    [{"full_name": "dosibjrn/duplicate", "private": False}] * 2,
    {"not": "a list"},
])
def test_public_owner_discovery_fails_closed_on_ambiguous_input(page):
    with pytest.raises(ValueError):
        module.discover_public_owner_repos(lambda _page: page)


def test_failed_owner_discovery_still_inspects_core_without_clearance(monkeypatch, capsys):
    monkeypatch.setattr(module, "github_owner_page",
                        lambda _page: (_ for _ in ()).throw(OSError("forbidden")))
    monkeypatch.setattr(module, "github_page",
                        lambda _repo, _page: {"total_count": 0, "artifacts": []})
    assert module.main() == 1
    out = capsys.readouterr().out
    assert out.count("RETAINED repo=") == 2
    assert "PUBLIC_OWNER_REPOS_UNKNOWN" in out
    assert "RETAINED_SCOPE=INCOMPLETE" in out
    assert "RETAINED_PUBLIC_OWNER_REPOS count=" not in out


def test_public_owner_total_includes_other_repositories(monkeypatch, capsys):
    monkeypatch.setattr(module, "github_owner_page", lambda _page: [
        {"full_name": "dosibjrn/other-repo", "private": False}])
    monkeypatch.setattr(module, "github_page", lambda repo, _page: {
        "total_count": 1, "artifacts": [
            {"id": 1, "size_in_bytes": 2048 if repo.endswith("other-repo") else 512}]})
    assert module.main() == 0
    out = capsys.readouterr().out
    assert "RETAINED_KNOWN_TWO_REPOS bytes=1024" in out
    assert "RETAINED_PUBLIC_OWNER_REPOS count=3 bytes=3072" in out
    assert "BILLING_METER=UNKNOWN" in out


@pytest.mark.parametrize(("retained", "expected"), [
    (0, 0),
    (374_999_999, 0),
    (375_000_000, 75),
    (424_999_999, 75),
    (425_000_000, 85),
    (449_999_999, 85),
    (450_000_000, 90),
    (700_000_000, 90),
])
def test_nominal_retained_reference_levels_are_exact_not_billing(retained, expected):
    assert module.retained_reference_level(retained) == expected


def test_retained_reference_rejects_negative_bytes():
    with pytest.raises(ValueError, match="negative"):
        module.retained_reference_level(-1)


def test_large_public_retained_footprint_warns_without_claiming_billing_clearance(monkeypatch, capsys):
    monkeypatch.setattr(module, "github_owner_page", lambda _page: [
        {"full_name": repo, "private": False} for repo in module.REPOSITORIES])
    monkeypatch.setattr(module, "github_page", lambda _repo, _page: {
        "total_count": 1, "artifacts": [{"id": 1, "size_in_bytes": 300_000_000}]})
    assert module.main() == 0
    output = capsys.readouterr().out
    assert "RETAINED_REFERENCE_LEVEL=90" in output
    assert "::warning::RETAINED_REFERENCE_90_PCT" in output
    assert "BILLING_METER=UNKNOWN" in output
    assert "RETAINED_PUBLIC_OWNER_REPOS count=2 bytes=600000000" in output


def test_gc_fast_noop_skips_if_below_ceiling_or_only_newest_five_can_age():
    import datetime as dt

    now = dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=72)
    recent = now - dt.timedelta(hours=1)
    old = now - dt.timedelta(days=5)
    make = lambda stamp: {"created_at": stamp.isoformat()}
    created = lambda artifact: dt.datetime.fromisoformat(artifact["created_at"])
    newest_five = [make(recent)] * 4 + [make(old)]
    assert not module.requires_evidence_pin_scan(300, 384, [*newest_five, make(old)], cutoff, created)
    assert not module.requires_evidence_pin_scan(500, 384, newest_five, cutoff, created)
    assert not module.requires_evidence_pin_scan(500, 384, [*newest_five, make(cutoff)], cutoff, created)
    assert module.requires_evidence_pin_scan(500, 384, [*newest_five, make(old)], cutoff, created)


def test_live_storage_guard_skips_pin_api_only_when_no_delete_can_be_planned():
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
                    encoding="utf-8")
    fast_noop = "if not requires_evidence_pin_scan(total, ceiling, stage5, cutoff, created):"
    assert fast_noop in workflow
    assert workflow.index("return verified_artifacts(repo, fetch_page)") < workflow.index(fast_noop)
    assert workflow.index(fast_noop) < workflow.index("collect_local_references(")
    assert workflow.index(fast_noop) < workflow.index('gh_collection("issues?state=all")')
    assert workflow.index(fast_noop) < workflow.index('request(f"artifacts/{aid}", "DELETE")')


def test_public_fork_artifacts_retry_anonymously_after_scoped_token_404(monkeypatch, capsys):
    """Do not treat public Rust-fork bytes as unknown solely due to repo-scoped auth."""
    monkeypatch.setenv("GH_TOKEN", "only-current-repository")
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        assert timeout == 25
        if len(requests) == 1:
            assert request.get_header("Authorization") == "Bearer only-current-repository"
            raise urllib.error.HTTPError(request.full_url, 404, "scoped token", {}, None)
        assert request.get_header("Authorization") is None
        return io.BytesIO(b'{"total_count":1,"artifacts":[{"id":9,"size_in_bytes":1234}]}')

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    assert module.inventory(
        "dosibjrn/mythicsim-forever-engine", module.github_page) == (1, 1234)
    assert len(requests) == 2
    assert "PUBLIC_READ_FALLBACK repo=mythicsim-forever-engine" in capsys.readouterr().out


def test_failed_anonymous_retry_does_not_report_public_fork_headroom(monkeypatch, capsys):
    """If both token and anonymous public reads fail, scope remains incomplete."""
    monkeypatch.setenv("GH_TOKEN", "only-current-repository")
    monkeypatch.setattr(module, "github_owner_page", lambda page: [
        {"full_name": repo, "private": False} for repo in module.REPOSITORIES])
    calls = []

    def urlopen(request, timeout):
        calls.append(request)
        if "forever-sim/actions" in request.full_url:
            return io.BytesIO(b'{"total_count":0,"artifacts":[]}')
        raise urllib.error.HTTPError(request.full_url, 404, "unavailable", {}, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    assert module.main() == 1
    output = capsys.readouterr().out
    assert "RETAINED_SCOPE=INCOMPLETE" in output
    assert "RETAINED_PUBLIC_OWNER_REPOS count=" not in output
    # One authenticated attempt and exactly one unauthenticated public retry.
    fork_requests = [req for req in calls if "mythicsim-forever-engine" in req.full_url]
    assert len(fork_requests) == 2
    assert fork_requests[0].get_header("Authorization")
    assert fork_requests[1].get_header("Authorization") is None


def test_non_public_artifact_url_never_retries_anonymously(monkeypatch):
    """Restrict fallback to known public owner artifact-list GETs."""
    monkeypatch.setenv("GH_TOKEN", "scoped-token")
    calls = []

    def urlopen(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        module._github_json("https://api.github.com/repos/another/private/actions/artifacts")
    assert len(calls) == 1
