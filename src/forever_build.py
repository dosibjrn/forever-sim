from __future__ import annotations

"""Process-wide WoW: Forever beta build identity.

Forever is a moving beta target.  Every production run therefore resolves one
explicit ``as_of`` date and exports it to child processes.  Pre-v0.11.48.74
artifacts had an implicit release snapshot; they are mapped to that historical
snapshot deliberately instead of being reinterpreted as whatever build is
current later.
"""

from dataclasses import dataclass
from datetime import date
import os
from typing import Any, Mapping

FOREVER_BUILD_ENV = "WOW_FOREVER_BUILD_AS_OF"
FOREVER_BUILD_SOURCE_ENV = "WOW_FOREVER_BUILD_SOURCE"
LEGACY_COMPAT_AS_OF = date(2026, 10, 2)
BUILD_ID_SCHEMA_VERSION = 1


def parse_as_of(value: date | str) -> date:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("Forever build/as-of must be YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid Forever build/as-of {value!r}; expected YYYY-MM-DD") from exc


@dataclass(frozen=True)
class ForeverBuildIdentity:
    as_of: date
    source: str
    schema_version: int = BUILD_ID_SCHEMA_VERSION

    @property
    def build_id(self) -> str:
        return f"forever-beta@{self.as_of.isoformat()}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "build_id": self.build_id,
            "as_of": self.as_of.isoformat(),
            "source": self.source,
        }


def configure(value: date | str | None, *, source: str | None = None) -> ForeverBuildIdentity:
    if value is None or not str(value).strip():
        resolved = LEGACY_COMPAT_AS_OF
        resolved_source = source or "legacy_compat_default"
    else:
        resolved = parse_as_of(value)
        resolved_source = source or "explicit"
    os.environ[FOREVER_BUILD_ENV] = resolved.isoformat()
    os.environ[FOREVER_BUILD_SOURCE_ENV] = str(resolved_source)
    return ForeverBuildIdentity(resolved, str(resolved_source))


def current() -> ForeverBuildIdentity:
    raw = os.environ.get(FOREVER_BUILD_ENV)
    if raw:
        return ForeverBuildIdentity(
            parse_as_of(raw), os.environ.get(FOREVER_BUILD_SOURCE_ENV) or "environment"
        )
    return ForeverBuildIdentity(LEGACY_COMPAT_AS_OF, "legacy_compat_default")


def metadata() -> dict[str, Any]:
    return current().as_dict()


def canonical_request_as_of(ruleset: str, value: date | str | None) -> str | None:
    if str(ruleset).strip().lower() != "forever":
        if value not in (None, ""):
            raise ValueError("forever_build_as_of is valid only for the forever ruleset")
        return None
    if value is None or not str(value).strip():
        return LEGACY_COMPAT_AS_OF.isoformat()
    return parse_as_of(value).isoformat()


def request_identity(request: Mapping[str, Any]) -> tuple[str | None, bool]:
    """Return canonical request build date and whether legacy compatibility was used."""
    if str(request.get("ruleset") or "").lower() != "forever":
        return None, False
    raw = request.get("forever_build_as_of")
    if raw is None or not str(raw).strip():
        return LEGACY_COMPAT_AS_OF.isoformat(), True
    return parse_as_of(raw).isoformat(), False
