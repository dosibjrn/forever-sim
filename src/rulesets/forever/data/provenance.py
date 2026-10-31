from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


_WOWHEAD_ID_RE = re.compile(r"https?://(?:www\.)?wowhead\.com/forever/(?:spell|item)=(\d+)(?:[/?#-]|$)", re.I)


def wowhead_id_from_url(url: str) -> int | None:
    m = _WOWHEAD_ID_RE.search(str(url or ""))
    return int(m.group(1)) if m else None


def stable_json_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
