"""Read-only retained artifact footprint for the two owned production repositories.

This is NOT an Actions billing/GB-month meter, and never deletes artifacts.
The in-repository evidence-aware GC remains the only deletion path.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

REPOSITORIES = ("dosibjrn/forever-sim", "dosibjrn/mythicsim-forever-engine")
PAGE_LIMIT = 100


def inventory(repository: str, fetch_page) -> tuple[int, int]:
    """Require complete, nonduplicate pagination; fail rather than undercount."""
    seen: set[int] = set()
    total_bytes = 0
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
        for artifact in payload["artifacts"]:
            if not isinstance(artifact, dict):
                raise ValueError(f"{repository}: malformed artifact on page {page}")
            aid, size = artifact.get("id"), artifact.get("size_in_bytes")
            if (type(aid) is not int or aid < 1 or aid in seen
                    or type(size) is not int or size < 0):
                raise ValueError(f"{repository}: duplicate/invalid artifact on page {page}")
            seen.add(aid)
            total_bytes += size
        if len(payload["artifacts"]) < 100:
            if len(seen) != expected:
                raise ValueError(f"{repository}: pagination changed: {len(seen)} != {expected}")
            return len(seen), total_bytes
    raise ValueError(f"{repository}: pagination exceeded {PAGE_LIMIT} pages")


def github_page(repository: str, page: int) -> dict:
    token = os.environ.get("GH_TOKEN", "")
    url = (f"https://api.github.com/repos/{repository}/actions/artifacts"
           f"?per_page=100&page={page}")
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def main() -> int:
    totals = []
    failed = []
    for repository in REPOSITORIES:
        try:
            count, size = inventory(repository, github_page)
            print(f"RETAINED repo={repository} artifacts={count} bytes={size} MiB={size/1048576:.2f}")
            totals.append(size)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"::warning::RETAINED_UNKNOWN repo={repository}: {exc}")
            failed.append(repository)
    if failed:
        print("RETAINED_SCOPE=INCOMPLETE; no account-wide headroom claim")
        return 1
    print(f"RETAINED_KNOWN_TWO_REPOS bytes={sum(totals)} MiB={sum(totals)/1048576:.2f}")
    print("BILLING_METER=UNKNOWN; retained bytes are not billed GB-months; other repos/packages/caches omitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
