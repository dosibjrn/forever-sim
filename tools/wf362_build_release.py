"""Package only material WF362 changes, no baseline-version inflation."""
from __future__ import annotations
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=Path('/mnt/data/wf362_outputs')
NAME='WF362_WARRIOR_L30_P2_117_OF_117_ON_WF361.zip'
FILES=[
 'src/game/data/forever/source_checkpoint_talent_stage.py',
 'src/game/data/forever/source_talent_overlay.py',
 'src/game/data/forever/source_checkpoint_p2.py',
 'tools/wf362_stage_warrior30_talents.py',
 'tools/wf362_warrior_l30_p2_acceptance.py',
 'tools/wf362_build_release.py',
 'tests/test_wf362_warrior_l30_p2.py',
 'data/forever/staged_warrior_l30_talents_70338.sqlite',
 'evidence/wf362/warrior_l30_source_talent_catalogue_70338.json',
 'evidence/wf362/WF362_WARRIOR_L30_P2_CERTIFICATE.json',
 'WF362_HANDOVER_2026-10-14.md','WF362_VALIDATION.json']
def run():
 OUT.mkdir(exist_ok=True)
 path=OUT/NAME
 with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
  for rel in FILES:z.write(ROOT/rel,arcname=rel)
 with zipfile.ZipFile(path) as z:
  assert z.testzip() is None
  assert set(z.namelist())==set(FILES)
 sha=hashlib.sha256(path.read_bytes()).hexdigest()
 (OUT/'WF362_ZIP_SHA256.txt').write_text(f'{sha}  {NAME}\n')
 for file in ['WF362_HANDOVER_2026-10-14.md','WF362_VALIDATION.json']:
  (OUT/file).write_bytes((ROOT/file).read_bytes())
 return {'archive':str(path),'sha256':sha,'files':len(FILES),'size_bytes':path.stat().st_size}
if __name__=='__main__':print(json.dumps(run(),indent=2))
