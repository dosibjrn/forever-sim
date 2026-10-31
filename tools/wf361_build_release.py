"""Reproducible WF361 overlay packager. Apply once on Library WF360."""
from __future__ import annotations
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=Path('/mnt/data/wf361_outputs')
NAME='WF361_WARRIOR_L30_P1_54_OF_54_ON_WF360.zip'
FILES=(
 'src/game/data/forever/warrior.py',
 'src/game/data/forever/registry.py',
 'src/game/data/forever/source_checkpoint_p1_acceptance.py',
 'src/game/data/forever/source_checkpoint_spellbook.py',
 'tools/wf361_warrior_l30_p1.py',
 'tools/wf361_build_release.py',
 'tests/test_wf361_warrior_l30_p1.py',
 'evidence/wf361/warrior_spellbook_70338_level1_30.json',
 'evidence/wf361/WF361_WARRIOR_L30_P1_CERTIFICATE.json',
 'WF361_HANDOVER_2026-10-14.md',
 'WF361_VALIDATION.json',
)
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/NAME
    with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for rel in FILES:
            data=(ROOT/rel).read_bytes()
            info=zipfile.ZipInfo(rel,date_time=(2026,10,14,5,55,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(p) as z:
        assert z.testzip() is None
        assert set(z.namelist())==set(FILES)
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT/'WF361_ZIP_SHA256.txt').write_text(sha+'  '+NAME+'\n')
    for name in ('WF361_HANDOVER_2026-10-14.md','WF361_VALIDATION.json'):
        (OUT/name).write_bytes((ROOT/name).read_bytes())
    print(json.dumps({'zip':str(p),'sha256':sha,'files':len(FILES),'bytes':p.stat().st_size}))
if __name__=='__main__':main()
