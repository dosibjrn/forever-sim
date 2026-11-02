"""G46f release snapshots must match actual authority before HTTP requests."""
import json
from pathlib import Path
from src.version import SOFTWARE_VERSION
from src.v2.generic_frontier import (ROUTE_PUBLICATION_CACHE_PATH, generic_druid_route_publication)
from src.v2.generic_melee_routes import (MELEE_CACHE_PATH, generic_melee_route_publication, _fingerprint)


def test_release_route_snapshots_are_validated_without_live_solve():
    druid = json.loads(Path(ROUTE_PUBLICATION_CACHE_PATH).read_text())
    melee = json.loads(Path(MELEE_CACHE_PATH).read_text())
    assert druid['software_version'] == melee['software_version'] == SOFTWARE_VERSION
    assert melee['source_code_fingerprint'] == _fingerprint()
    _, _, meta = generic_druid_route_publication()
    _, melee_meta = generic_melee_route_publication()
    assert meta['status'] == 'validated_release_snapshot'
    assert melee_meta['status'] == 'validated_release_snapshot'
