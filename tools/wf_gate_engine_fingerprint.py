"""Code fingerprint of acceptance-affecting game engine modules."""
from pathlib import Path
import hashlib

# P4/P5 must agree on source, runtime implementation and 100mob scenario.
# Neither paid search duration nor the winner is part of scenario identity.
_RUNTIME_MODULES = (
    'src/v2/source_bounded_joint_frontier.py',
    'src/game/runtime/simulator.py',
    'src/game/data/forever/registry.py',
    'src/game/talents.py',
    'src/game/model/ir.py',
    'tools/wf463_spec_druid_l30_search.py',
    'tools/wf_gate_engine_fingerprint.py',
)


def runtime_fingerprint(root: Path) -> str:
    d=hashlib.sha256()
    # Source tree hash: a change in *any* runtime dependency invalidates
    # cached results, not only changes to a small hand-picked module list.
    mandatory=[root/rel for rel in _RUNTIME_MODULES]
    for item in mandatory:
        if not item.is_file():
            raise FileNotFoundError('RUNTIME_CODE_FILE_MISSING:'+str(item))
    files={p for p in (root/'src').rglob('*.py') if p.is_file()}
    files.update(mandatory)
    for item in sorted(files):
        rel=item.relative_to(root).as_posix()
        d.update(rel.encode('utf8')+b'\0'+hashlib.sha256(item.read_bytes()).digest())
    return d.hexdigest()

