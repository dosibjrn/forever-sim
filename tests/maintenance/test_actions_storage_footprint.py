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
    assert "from tools.actions_storage_footprint import (verified_artifacts, requires_evidence_pin_scan," in workflow
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
    fast_noop = "if not requires_evidence_pin_scan(planning_total, ceiling, stage5, cutoff, created):"
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


def test_public_owner_repo_index_retries_anonymously_after_scoped_token_403(
        monkeypatch, capsys):
    """Discover all owned public repos even if the Actions token is repo-scoped."""
    monkeypatch.setenv("GH_TOKEN", "only-current-repository")
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        assert timeout == 25
        if len(requests) == 1:
            assert request.get_header("Authorization") == "Bearer only-current-repository"
            raise urllib.error.HTTPError(request.full_url, 403, "scoped token", {}, None)
        assert request.get_header("Authorization") is None
        return io.BytesIO(
            b'[{"full_name":"dosibjrn/third-public-repo","private":false}]')

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    found = module.discover_public_owner_repos(module.github_owner_page)
    assert len(requests) == 2
    assert set(module.REPOSITORIES).issubset(found)
    assert "dosibjrn/third-public-repo" in found
    assert "PUBLIC_READ_FALLBACK owner-repos=dosibjrn" in capsys.readouterr().out


def test_owner_index_anonymous_failure_remains_unverified(monkeypatch, capsys):
    """A second 403 still fails closed; do not invent account headroom."""
    monkeypatch.setenv("GH_TOKEN", "only-current-repository")
    calls = []

    def urlopen(request, timeout):
        calls.append(request)
        if "/users/" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 403, "denied", {}, None)
        return io.BytesIO(b'{"total_count":0,"artifacts":[]}')

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "RETAINED_SCOPE=INCOMPLETE" in out
    assert "RETAINED_PUBLIC_OWNER_REPOS count=" not in out
    owner_requests = [req for req in calls if "/users/dosibjrn/repos?" in req.full_url]
    assert len(owner_requests) == 2
    assert owner_requests[0].get_header("Authorization")
    assert owner_requests[1].get_header("Authorization") is None


@pytest.mark.parametrize("url", [
    "https://api.github.com/users/somebody/repos?type=owner&per_page=100&page=1",
    "https://api.github.com/users/dosibjrn/repos?type=all&per_page=100&page=1",
    "https://api.github.com/users/dosibjrn/repos?type=owner&per_page=100&page=1&private=1",
])
def test_public_owner_fallback_never_reads_foreign_or_other_scopes(
        monkeypatch, url):
    monkeypatch.setenv("GH_TOKEN", "scoped-token")
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        raise urllib.error.HTTPError(request.full_url, 403, "denied", {}, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        module._github_json(url)
    assert len(requests) == 1


def test_post_delete_retries_unstable_pagination_then_stale_id_without_false_success():
    """A moving GitHub page count is retryable only in post-DELETE verification."""
    calls = []
    sleeps = []

    def list_verified():
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            def moving(_repo, page):
                if page == 1:
                    return {"total_count": 101,
                            "artifacts": [{"id": i, "size_in_bytes": 1}
                                          for i in range(1, 101)]}
                return {"total_count": 100, "artifacts": [{"id": 101, "size_in_bytes": 1}]}
            return module.verified_artifacts("owner/repo", moving)
        if len(calls) == 2:
            return [{"id": 55, "size_in_bytes": 100},
                    {"id": 70, "size_in_bytes": 1}]
        return [{"id": 70, "size_in_bytes": 1}]

    after = module.verify_deleted_artifacts_absent(
        [55], list_verified, attempts=4, delay_seconds=5,
        sleep=sleeps.append)
    assert after == [{"id": 70, "size_in_bytes": 1}]
    assert calls == [1, 2, 3]
    assert sleeps == [5, 5]


def test_post_delete_never_certifies_partial_inventories():
    """Repeated pagination churn exhausts the bounded retries and fails closed."""
    calls = []
    sleeps = []

    def unstable():
        calls.append(1)
        raise ValueError("total_count changed during pagination")

    with pytest.raises(RuntimeError, match="did not converge"):
        module.verify_deleted_artifacts_absent(
            [55], unstable, attempts=3, delay_seconds=2,
            sleep=sleeps.append)
    assert len(calls) == 3
    assert sleeps == [2, 2]


def test_post_delete_visible_id_still_fails_closed():
    calls = []
    with pytest.raises(RuntimeError, match="last-visible IDs=\\[55\\]"):
        module.verify_deleted_artifacts_absent(
            [55], lambda: calls.append(1) or [{"id": 55, "size_in_bytes": 1}],
            attempts=2, delay_seconds=0, sleep=lambda _seconds: None)
    assert len(calls) == 2


def test_live_gc_invokes_bounded_complete_post_delete_verification():
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
                    encoding="utf-8")
    assert "gc_planning_reference, verify_deleted_artifacts_absent," in workflow
    assert "verified_removed_footprint)" in workflow
    assert "after_artifacts = verify_deleted_artifacts_absent(" in workflow
    assert "deleted + already_absent, list_artifacts, attempts=12, delay_seconds=5," in workflow
    assert "fetch_deleted_status=deleted_artifact_get_status)" in workflow
    assert 'status, _ = request(f"artifacts/{artifact_id}")' in workflow
    assert workflow.index('request(f"artifacts/{aid}", "DELETE")') < workflow.index(
        "after_artifacts = verify_deleted_artifacts_absent(")


def test_post_delete_direct_get_must_converge_to_404_as_well_as_list_absence():
    """A temporarily stale GET=200 cannot certify the vanished list entry."""
    gets = []
    sleeps = []
    responses = iter((200, 404))

    def artifact_status(artifact_id):
        gets.append(artifact_id)
        return next(responses)

    after = module.verify_deleted_artifacts_absent(
        [55], lambda: [{"id": 70, "size_in_bytes": 5}],
        attempts=3, delay_seconds=2, sleep=sleeps.append,
        fetch_deleted_status=artifact_status)
    assert after == [{"id": 70, "size_in_bytes": 5}]
    assert gets == [55, 55]
    assert sleeps == [2]


def test_post_delete_does_not_get_or_certify_ids_still_in_inventory():
    """Direct GET cannot override an incomplete post-DELETE list."""
    gets = []
    with pytest.raises(RuntimeError, match="last-visible IDs=\\[55\\]"):
        module.verify_deleted_artifacts_absent(
            [55], lambda: [{"id": 55, "size_in_bytes": 5}],
            attempts=2, delay_seconds=0, sleep=lambda _seconds: None,
            fetch_deleted_status=lambda artifact_id: gets.append(artifact_id) or 404)
    assert gets == []


@pytest.mark.parametrize("status", [401, 403, 429, 500, None, "404"])
def test_post_delete_unexpected_direct_get_status_fails_closed(status):
    """Only HTTP 404 certifies gone; rate limits and auth failures never pass."""
    with pytest.raises(RuntimeError, match="unexpected GET HTTP"):
        module.verify_deleted_artifacts_absent(
            [55], lambda: [], attempts=3, delay_seconds=0,
            sleep=lambda _seconds: None,
            fetch_deleted_status=lambda _artifact_id: status)


def test_post_delete_checks_every_id_on_each_complete_snapshot():
    calls = []
    responses = {7: [404, 404], 8: [200, 404]}
    def get(artifact_id):
        calls.append(artifact_id)
        return responses[artifact_id].pop(0)

    assert module.verify_deleted_artifacts_absent(
        [7, 8], lambda: [], attempts=3, delay_seconds=0,
        sleep=lambda _seconds: None, fetch_deleted_status=get) == []
    assert calls == [7, 8, 7, 8]


def test_gc_planning_reference_uses_complete_owner_bytes_not_billing():
    assert module.gc_planning_reference(200, "450000000") == (450000000, True)
    assert module.gc_planning_reference(450, "200") == (450, False)
    assert module.gc_planning_reference(200, "") == (200, False)
    assert module.gc_planning_reference(200, "not available") == (200, False)
    assert module.gc_planning_reference(200, "2e8") == (200, False)
    assert module.gc_planning_reference(200, "-1") == (200, False)
    with pytest.raises(ValueError, match="invalid local"):
        module.gc_planning_reference(-1, "100")


def test_owner_monitor_writes_signal_only_after_complete_inventory(
        monkeypatch, tmp_path):
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(module, "github_owner_page", lambda _page: [
        {"full_name": repo, "private": False} for repo in module.REPOSITORIES])
    monkeypatch.setattr(module, "github_page", lambda _repo, _page: {
        "total_count": 1, "artifacts": [{"id": 1, "size_in_bytes": 42}]})
    assert module.main() == 0
    assert output.read_text() == "retained_public_bytes=84\n"

    output.unlink()
    monkeypatch.setattr(module, "github_page", lambda repo, _page: (
        (_ for _ in ()).throw(OSError("fork unavailable"))
        if repo.endswith("mythicsim-forever-engine") else {
            "total_count": 1, "artifacts": [{"id": 1, "size_in_bytes": 42}]}))
    assert module.main() == 1
    assert not output.exists()


def test_live_gc_consumes_complete_owner_total_and_bounds_deletions():
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
                    encoding="utf-8")
    assert "id: footprint" in workflow
    assert "steps.footprint.outputs.retained_public_bytes" in workflow
    assert "gc_planning_reference(" in workflow
    assert "requires_evidence_pin_scan(planning_total, ceiling" in workflow
    assert "remaining = planning_total" in workflow
    assert "owner_scope and len(planned) >= 10" in workflow
    assert workflow.index("collect_local_references(") < workflow.index("planned = []")
    assert workflow.index("completed_run_candidates(") < workflow.index("planned = []")


def test_verified_reclaim_separates_selected_deletion_from_concurrent_uploads():
    before = [
        {"id": 10, "size_in_bytes": 100},
        {"id": 20, "size_in_bytes": 50},
    ]
    # The intended 100-byte deletion succeeded, but another workflow
    # uploaded 400 bytes. The repository's net retained bytes *grew* by 300.
    after_upload = [
        {"id": 20, "size_in_bytes": 50},
        {"id": 30, "size_in_bytes": 400},
    ]
    assert module.verified_removed_footprint(
        before, after_upload, [10]) == (100, -300)

    # An independent expiry must not be attributed to this GC's deletion.
    assert module.verified_removed_footprint(before, [], [10]) == (100, 150)


@pytest.mark.parametrize(("deleted", "after"), [
    ([99], []),  # Not in the original complete inventory.
    ([10], [{"id": 10, "size_in_bytes": 100}]),  # Not actually absent.
    ([10, 10], []),  # Duplicate DELETE targets must not double-count bytes.
])
def test_verified_reclaim_rejects_unproven_or_duplicate_targets(deleted, after):
    with pytest.raises(ValueError):
        module.verified_removed_footprint(
            [{"id": 10, "size_in_bytes": 100}], after, deleted)


def test_live_gc_reports_targeted_removals_and_net_change_separately():
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
                    encoding="utf-8")
    assert "verified_removed_footprint(" in workflow
    assert "VERIFIED_TARGET_REMOVALS" in workflow
    assert "RETAINED_NET_DELTA" in workflow
    assert "planning_total - targeted_bytes" in workflow
    assert 'reclaimed_MiB={(total-after)' not in workflow
    assert workflow.index("verify_deleted_artifacts_absent(") < workflow.index(
        "verified_removed_footprint(")


def test_gc_only_credits_successful_204_deletes_not_concurrently_absent_404():
    """A vanished artifact cannot be billed as reclaimed by this GC run.

    Both statuses need a verified post-DELETE absence, but targeted bytes must
    count only IDs for which our own authenticated DELETE returned HTTP 204.
    This is storage-report accuracy, not an additional M1 gate.
    """
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
                    encoding="utf-8")
    assert workflow.index("if status == 204:") < workflow.index("deleted.append(aid)")
    assert 'elif status == 404:' in workflow
    assert 'already_absent.append(aid)' in workflow
    assert 'deleted + already_absent, list_artifacts' in workflow
    assert 'all_artifacts, after_artifacts, deleted)' in workflow
    assert 'if status not in (204, 404):' not in workflow
    assert workflow.index('deleted + already_absent, list_artifacts') < workflow.index(
        'all_artifacts, after_artifacts, deleted)')

def test_concurrent_artifact_expiry_not_misattributed_to_gc_deleted_bytes():
    """Confirmed DELETE IDs and other vanished IDs have distinct accounting."""
    before = [{"id": 11, "size_in_bytes": 200},
              {"id": 12, "size_in_bytes": 350}]
    assert module.verified_removed_footprint(before, [], [11]) == (200, 550)


def test_storage_guard_source_changes_trigger_maintenance_ci():
    """Production inventory, pin protection and GC edits must run safety tests on PRs."""
    workflow = (Path(__file__).resolve().parents[2]
                / ".github/workflows/maintenance-evidence-tests.yml").read_text(
                    encoding="utf-8")
    pr_paths = workflow.split("  pull_request:\n", 1)[1].split("\npermissions:", 1)[0]
    for file in (
        "tools/actions_storage_footprint.py",
        "tools/actions_artifact_pins.py",
        ".github/workflows/actions-storage-preventive-gc.yml",
        "tests/maintenance/**",
    ):
        assert f"      - '{file}'\\n".replace("\\n", "\n") in pr_paths, file
