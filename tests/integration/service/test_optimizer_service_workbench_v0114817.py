from pathlib import Path

from src.service.models import JobRequest
from src.service.store import QueueStore


def _req(cls='mage'):
    return JobRequest(ruleset='forever', class_name=cls, start_level=20, end_level=20, endpoint_mode='fast')


def test_lineage_groups_attempt_checkpoints_and_publications(tmp_path: Path):
    store=QueueStore(tmp_path/'queue.sqlite3')
    job,_=store.enqueue(_req())
    job,attempt=store.claim_next(owner='w',runs_root=tmp_path/'runs',lease_seconds=60)
    cp_path=Path(attempt['run_root'])/'state.json'; cp_path.write_text('{}')
    cp=store.record_checkpoint({'job_id':job['id'],'attempt_id':attempt['id'],'path':str(cp_path),'kind':'state','sha256':'x','size_bytes':2,'request':job['request'],'created_at':1.0})
    pub={'id':'pub1','job_id':job['id'],'attempt_id':attempt['id'],'state_root':'/published/pub1','parent_id':None,'request':job['request'],'created_at':2.0}
    store.record_publication(pub)
    lineage=store.job_lineage(job['id'])
    assert lineage['publication_count']==1
    assert lineage['latest_publication']['id']=='pub1'
    assert lineage['attempts'][0]['checkpoints'][0]['id']==cp['id']
    assert lineage['attempts'][0]['publications'][0]['id']=='pub1'


def test_publication_history_filters_selected_class_without_hiding_last_good(tmp_path: Path):
    store=QueueStore(tmp_path/'queue.sqlite3')
    for cls,pid in [('mage','pm'),('druid','pd')]:
        job,_=store.enqueue(_req(cls))
        job,attempt=store.claim_next(owner='w',runs_root=tmp_path/'runs',lease_seconds=60)
        store.record_publication({'id':pid,'job_id':job['id'],'attempt_id':attempt['id'],'state_root':'/x','parent_id':None,'request':job['request'],'created_at':2.0 if cls=='druid' else 1.0})
        store.finish_attempt(attempt['id'],owner='w',outcome='completed')
    # A new Mage run can be active without replacing/hiding the previous Mage publication.
    store.enqueue(_req('mage'),deduplicate=False)
    pubs=store.list_publications(class_name='mage')
    assert [p['id'] for p in pubs]==['pm']
