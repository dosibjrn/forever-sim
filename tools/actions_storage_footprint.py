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
    with urllib.request.urlopen(request, timeout=25) as response:
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
    print("BILLING_METER=UNKNOWN; public retained bytes are not billed GB-months; private repos/packages/caches omitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
