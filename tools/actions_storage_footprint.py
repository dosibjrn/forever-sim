"""Read-only retained artifact footprint for the owner's public repositories.

This is NOT an Actions billing/GB-month meter, and never deletes artifacts.
The in-repository evidence-aware GC remains the only deletion path.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

OWNER = "dosibjrn"
REPOSITORIES = ("dosibjrn/forever-sim", "dosibjrn/mythicsim-forever-engine")
PAGE_LIMIT = 100


# Nominal included allowance from owner issue #1102 (0.5 GB decimal).
# This is only a retained-byte reference, NOT the billed GB-months meter.
INCLUDED_REFERENCE_BYTES = 500_000_000


def retained_reference_level(retained_bytes: int) -> int:
    """Warning threshold of visible retained bytes relative to 0.5 GB.

    Never interpret a value below a threshold as billing clearance: private
    repositories, caches, Packages and accrued storage are not in this scan.
    """
    if retained_bytes < 0:
        raise ValueError("negative retained-byte count")
    for threshold in (90, 85, 75):
        if retained_bytes * 100 >= INCLUDED_REFERENCE_BYTES * threshold:
            return threshold
    return 0


def verified_artifacts(repository: str, fetch_page) -> list[dict]:
    """Return a complete stable artifact snapshot; never approve partial GC input."""
    seen: set[int] = set()
    artifacts: list[dict] = []
    expected = None
    for page in range(1, PAGE_LIMIT + 1):
        payload = fetch_page(repository, page)
        if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
            raise ValueError(f"{repository}: malformed artifacts page {page}")
        count = payload.get("total_count")
        if type(count) is not int or count < 0:
            raise ValueError(f"{repository}: invalid total_count on page {page}")
        if expected is None:
            expected = count
        elif count != expected:
            raise ValueError(f"{repository}: total_count changed during pagination: {expected} -> {count}")
        batch = payload["artifacts"]
        if len(batch) > 100:
            raise ValueError(f"{repository}: oversized artifact page {page}")
        for artifact in batch:
            if not isinstance(artifact, dict):
                raise ValueError(f"{repository}: malformed artifact on page {page}")
            aid, size = artifact.get("id"), artifact.get("size_in_bytes")
            if (type(aid) is not int or aid < 1 or aid in seen
                    or type(size) is not int or size < 0):
                raise ValueError(f"{repository}: duplicate/invalid artifact on page {page}")
            seen.add(aid)
            artifacts.append(artifact)
        if len(batch) < 100:
            if len(seen) != expected:
                raise ValueError(f"{repository}: pagination changed: {len(seen)} != {expected}")
            return artifacts
    raise ValueError(f"{repository}: pagination exceeded {PAGE_LIMIT} pages")


def requires_evidence_pin_scan(total_bytes: int, ceiling_bytes: int,
                               newest_first_stage5: list[dict], cutoff,
                               created) -> bool:
    """Skip costly pin API reads only if no stage5 DELETE could be planned.

    The guard always protects the newest five stage5 artifacts. All other
    artifacts younger than the 72-hour cutoff are protected as well. An
    over-ceiling inventory with any older candidate still needs the complete
    evidence scan, even when that candidate ultimately proves pinned.
    """
    if total_bytes <= ceiling_bytes:
        return False
    return any(created(artifact) < cutoff for artifact in newest_first_stage5[5:])



def verify_deleted_artifacts_absent(deleted_ids, list_artifacts, *,
                                    attempts: int = 12,
                                    delay_seconds: float = 5,
                                    sleep=None,
                                    fetch_deleted_status=None) -> list[dict]:
    """Certify post-DELETE absence using a COMPLETE, stable inventory.

    GitHub can temporarily expose stale artifact pages after DELETE 204;
    pagination may also change counts mid-scan while the deletion propagates.
    Retry *only after deletion*, never when constructing the deletion plan:
    the pre-delete verified_artifacts() snapshot must still fail closed.
    An API or provenance error other than transient inventory ValueError
    propagates immediately. Never claim success from a partial inventory.
    When supplied, fetch_deleted_status(id) must also return HTTP 404 for
    every deleted ID; a briefly stale direct GET=200 is retryable, but an
    unexpected status fails closed. The production GC supplies this callback.
    """
    import time

    if type(attempts) is not int or attempts < 1:
        raise ValueError("verification attempts must be positive")
    sleep = time.sleep if sleep is None else sleep
    deleted = set(deleted_ids)
    remaining = deleted.copy()
    for attempt in range(attempts):
        try:
            after = list_artifacts()
        except ValueError as exc:
            # verified_artifacts() rejects moving page counts/duplicate IDs.
            # Retry a fresh whole snapshot, not the failed partial page.
            print(f"Post-DELETE inventory not stable: {exc}; "
                  f"retry {attempt + 1}/{attempts}")
        else:
            remaining = deleted.intersection(int(row["id"]) for row in after)
            if not remaining:
                if fetch_deleted_status is None:
                    return after
                # An absent list entry alone can be a stale/moving view.
                # Demand the same GET=404 proof as the live disposal smoke.
                get_pending = set()
                for artifact_id in sorted(deleted):
                    status = fetch_deleted_status(artifact_id)
                    if status == 200:
                        get_pending.add(artifact_id)
                    elif status != 404:
                        raise RuntimeError(
                            f"artifact {artifact_id}: unexpected GET HTTP {status} "
                            "after DELETE")
                if not get_pending:
                    return after
                remaining = get_pending
                print(f"Direct GET still visible for {len(remaining)} deleted IDs; "
                      f"retry {attempt + 1}/{attempts}")
            else:
                print(f"Deletion pending visibility for {len(remaining)} IDs; "
                      f"retry {attempt + 1}/{attempts}")
        if attempt + 1 < attempts:
            sleep(delay_seconds)
    raise RuntimeError(
        f"DELETE verification did not converge after {attempts} complete "
        f"inventory attempts; last-visible IDs={sorted(remaining)[:12]}")



def gc_planning_reference(local_bytes: int, public_owner_bytes: str | None) -> tuple[int, bool]:
    """Use complete public-owner retained bytes for safe GC planning when known.

    An absent, malformed or stale prior owner snapshot falls back to the
    repository-local policy. The signal is NOT billed account usage and never
    grants permission to remove evidence.
    """
    if type(local_bytes) is not int or local_bytes < 0:
        raise ValueError("invalid local retained bytes")
    if (not isinstance(public_owner_bytes, str)
            or not public_owner_bytes.isascii()
            or not public_owner_bytes.isdecimal()):
        return local_bytes, False
    public = int(public_owner_bytes)
    if public < local_bytes:
        return local_bytes, False
    return public, True


def inventory(repository: str, fetch_page) -> tuple[int, int]:
    """Count bytes only from a verified complete retained-artifact snapshot."""
    artifacts = verified_artifacts(repository, fetch_page)
    return len(artifacts), sum(a["size_in_bytes"] for a in artifacts)


def discover_public_owner_repos(fetch_page) -> list[str]:
    """Include all visible owned public repos, not just the two main projects.

    This is an intentionally bounded public-only scope: private repos, Packages,
    caches and account billing are not represented. Malformed/incomplete
    pagination must never produce a reassuring owner-wide total.
    """
    seen: set[str] = set()
    repositories = set(REPOSITORIES)
    for page in range(1, PAGE_LIMIT + 1):
        batch = fetch_page(page)
        if not isinstance(batch, list) or len(batch) > 100:
            raise ValueError(f"owner repository listing: invalid page {page}")
        for row in batch:
            if not isinstance(row, dict):
                raise ValueError(f"owner repository listing: malformed repo on page {page}")
            full_name = row.get("full_name")
            if (not isinstance(full_name, str) or not full_name.startswith(f"{OWNER}/")
                    or row.get("private") is not False or full_name in seen):
                raise ValueError(f"owner repository listing: invalid/duplicate repo on page {page}")
            seen.add(full_name)
            repositories.add(full_name)
        if len(batch) < 100:
            return sorted(repositories)
    raise ValueError(f"owner repository listing exceeded {PAGE_LIMIT} pages")


def _github_json(url: str):
    token = os.environ.get("GH_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # A workflow's GITHUB_TOKEN has access to its own repository, but may
        # receive 403/404 for another public repository owned by the same user.
        # The footprint monitor only reads public artifact listings; retry
        # those GETs anonymously rather than silently losing the Rust fork.
        # Never use this fallback for arbitrary URLs, private data or writes.
        public_artifacts = (
            url.startswith(f"https://api.github.com/repos/{OWNER}/")
            and url.split("?", 1)[0].endswith("/actions/artifacts")
        )
        # GitHub's repository-scoped Actions token can also refuse the public
        # owner-repository index. Without this read-only fallback the monitor
        # cannot discover other owned public repositories and always reports
        # incomplete scope despite the index being anonymously accessible.
        owner_prefix = (
            f"https://api.github.com/users/{OWNER}/repos?"
            "type=owner&per_page=100&page="
        )
        public_owner_index = (url.startswith(owner_prefix)
                              and url[len(owner_prefix):].isascii()
                              and url[len(owner_prefix):].isdigit())
        if not (token and (public_artifacts or public_owner_index)
                and exc.code in (403, 404)):
            raise
        anonymous_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        anonymous_request = urllib.request.Request(url, headers=anonymous_headers)
        with urllib.request.urlopen(anonymous_request, timeout=25) as response:
            if public_owner_index:
                print(f"PUBLIC_READ_FALLBACK owner-repos={OWNER}")
            else:
                print(f"PUBLIC_READ_FALLBACK repo={url.split('/')[5]}")
            return json.load(response)


def github_owner_page(page: int) -> list[dict]:
    return _github_json(
        f"https://api.github.com/users/{OWNER}/repos?type=owner&per_page=100&page={page}")


def github_page(repository: str, page: int) -> dict:
    return _github_json(
        f"https://api.github.com/repos/{repository}/actions/artifacts"
        f"?per_page=100&page={page}")


def main() -> int:
    failed = []
    try:
        repositories = discover_public_owner_repos(github_owner_page)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"::warning::PUBLIC_OWNER_REPOS_UNKNOWN: {exc}")
        failed.append("public owner repository listing")
        # Continue to inspect both canonical repositories; never claim a
        # complete public-owner total from a failed or partial listing.
        repositories = list(REPOSITORIES)

    sizes = {}
    for repository in repositories:
        try:
            count, size = inventory(repository, github_page)
            print(f"RETAINED repo={repository} artifacts={count} bytes={size} MiB={size/1048576:.2f}")
            sizes[repository] = size
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"::warning::RETAINED_UNKNOWN repo={repository}: {exc}")
            failed.append(repository)
    if failed:
        print("RETAINED_SCOPE=INCOMPLETE; no public-owner or account-wide headroom claim")
        return 1
    core_total = sum(sizes[repository] for repository in REPOSITORIES)
    print(f"RETAINED_KNOWN_TWO_REPOS bytes={core_total} MiB={core_total/1048576:.2f}")
    total = sum(sizes.values())
    print(f"RETAINED_PUBLIC_OWNER_REPOS count={len(repositories)} bytes={total} MiB={total/1048576:.2f}")
    level = retained_reference_level(total)
    print(f"RETAINED_REFERENCE_LEVEL={level} public_bytes={total} "
          f"reference_bytes={INCLUDED_REFERENCE_BYTES} "
          f"percent={100 * total / INCLUDED_REFERENCE_BYTES:.1f}; not billing usage")
    if level:
        print(f"::warning::RETAINED_REFERENCE_{level}_PCT: "
              f"visible public-owner artifacts use at least {100 * total / INCLUDED_REFERENCE_BYTES:.1f}% "
              "of the nominal 0.5 GB included-storage reference; "
              "check actual account billing/budgets and protected evidence")
    print("BILLING_METER=UNKNOWN; public retained bytes are not billed GB-months; private repos/packages/caches omitted")
    # Only a fully enumerated public-owner snapshot is exported to GC.
    # Incomplete scans return earlier without publishing a false safe total.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"retained_public_bytes={total}\\n".replace("\\n", "\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
