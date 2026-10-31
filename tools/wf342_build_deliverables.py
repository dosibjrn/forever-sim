from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from hashlib import sha256
from datetime import datetime,timezone
import json
ROOT=Path(__file__).resolve().parents[1]
ART=Path('/mnt/data')
report=json.loads((ROOT/'evidence/wf342/WF342_PROVISIONAL_RATING_TOP5.json').read_text())
current=json.loads((ROOT/'evidence/wf341/WF341_RATING_WEIGHTED_TOP5.json').read_text())
from src.rulesets.forever.items.runtime_selection import available_items
items={int(i.item_id):i for i in available_items('druid',20,required_level_policy='observed')}
lines=['# WF342 — Druid L20 provisio-Top 5 / slotti','',
       '**Ei lopullisesti hyväksytty P3:** Forever 70338:n rating-kertoimia, defensen koko combat tablea tai kaikkia item-proceja ei ole lähdevahvistettu.',
       'Mallissa crit/hit/defense/dodge muunnetaan historiallisella (StatLogic/TBC) kertoimella ja sen vaikutus testataan oikealla 100 mobin CombatRuntimella.',
       'L0-pisteet ovat säästyneitä sekunteja per mob per rating-yksikkö. Positiivinen arvo on parempi.',
       'Top 5 on **provisionaalinen malliranking**, ei kaikkien itemien L2-ajojen tulos eikä lupaus todellisesta parhaasta.',
       '', '## 100 mobin mallinnetut rating-weightit', '',
       '| Stat | s/mob per +1 rating | Status |', '|---|---:|---|']
for k,v in current['rating_evidence'].items():
    lines.append(f"| {k} | {float(v['weight_s_saved_per_mob_per_unit']):.9f} | {v['status']}, historical analogue |")
lines.extend(['','## Kaikkien slottien Top 5 (provisionaalinen)',''])
for slot,r in report['slots'].items():
    lines.extend([f'### {slot}', '', '| Sija | Item | Item-ID | Mallipiste (s/mob) |', '|---:|---|---:|---:|'])
    # Ranking score is preserved in detail rows whenever the same item is in
    # Top5 known/uncertain; report full score through sourced stat arithmetic
    # on item vector and the independently measured build-local weights.
    from src.rulesets.forever.items.runtime_selection import item_vector
    raw_weights=report['stat_weights']['weights']
    for index,item_id in enumerate(r['historical_rating_sensitivity_top_ids'],1):
        item=items[int(item_id)]
        stats=item_vector(item)
        score=sum(float(v)*float(raw_weights[k]['weight_s_saved_per_mob_per_unit'])
                  for k,v in stats.items()
                  if raw_weights.get(k,{}).get('weight_s_saved_per_mob_per_unit') is not None)
        for rating in ('crit','hit','defense','dodge'):
            score+=float(getattr(item,rating) or 0.)*float(report['provisional_rating_weights'][rating])
        lines.append(f'| {index} | {str(item.name).replace("|","/")} | {int(item_id)} | {score:.6f} |')
    lines.append('')
lines.extend(['## Rajaukset','',
'- Painoarvot ovat kiinteälle tunnetulle Cat/Claw-buildille; buildin muuttuessa painot pitää mitata uudelleen.',
'- 255 itemissä on ratkaisemattomia muita vaikutuksia tai vahvistamaton rating. Top 5 voi muuttua niiden mallinnuksen jälkeen.',
'- Defense antaa sekä Dodge- että incoming-miss-vaikutuksen; parry/block, incoming crit suppression ja defense-skill rounding ovat vielä avoimia.',
'- Client-version 1.60.1.70338 tarkka rating-muunnostaulukko on **vahvistamatta**. Historiallinen analogia ei ole kanoninen pelitieto.',
'- Vanilla-/SoD-rune-efektit eivät ole vapaasti haettavia, use_runes=false.',
'- Tuotannon strict L2 ei saa hyväksyä provisionaalista rating-mallia todisteeksi oikeasta combat rating -kertoimesta.',
'', 'Lähteet: https://www.curseforge.com/wow/addons/statlogiclib ja https://warcraft.wiki.gg/wiki/Defense', ''])
(ART/'WF342_TOP5_RATING_APPROX_REPORT.md').write_text('\n'.join(lines))
validation={
 'schema':'wf342_provisional_ratings_v1','checkpoint':'druid:L20:unrestricted:use_runes_false',
 'published_base':'WF341 on WF340 (on WF339)',
 'p1':True,'p2':True,'p3_user_contract':False,'accepted_checkpoints':0,'total_checkpoints':148,
 'legal_item_count':1175,'slots':18,'uncertain_items':255,
 'stat_weights_s_saved_per_mob_per_rating':report['provisional_rating_weights'],
 'source_rating_conversion':'HISTORICAL_ANALOGUE_NOT_FOREVER_70338_VERIFIED',
 'executor_probes_100mobs':True,'test_count':46,'test_failed':0,
 'unchanged_prior_winner_100mob_s_per_mob':13.46412880141965,
 'equipped_item_crit_probe_100mobs':{'item_id':7348,'crit_rating':14,'without_rating_model':14.129452576870774,'provisional':13.476271852763146},
 'equipped_item_defense_probe_100mobs':{'item_id':12985,'defense_rating':4,'without_rating_model':14.135886690084908,'provisional':14.08564431965031},
 'provisional_top5_changed_slots':[slot for slot,v in report['slots'].items() if v['known_weight_top_ids']!=v['historical_rating_sensitivity_top_ids']],
 'new_strict_30s_300s_search':False,'can_be_claimed_as_full_l2':False,
 'open_defense_channels':['parry','block','incoming_crit_reduction','defense_skill_rounding'],
 'source_urls':['https://www.curseforge.com/wow/addons/statlogiclib','https://warcraft.wiki.gg/wiki/Defense'],
}
(ART/'WF342_VALIDATION.json').write_text(json.dumps(validation,indent=2,ensure_ascii=False))
files=['src/game/runtime/simulator.py','src/v2/source_persistent_joint_finalists.py',
       'src/game/data/forever/source_checkpoint_p3_ratings.py',
       'src/game/data/forever/source_checkpoint_p3_weights.py',
       'tests/test_wf341_rating_semantics.py',
       'tools/wf341_rating_probe.py','tools/wf341_defense_check.py',
       'tools/wf342_rating_report.py','tools/wf342_live_equipped_rating_demo.py',
       'evidence/wf341/WF341_RATING_WEIGHTED_TOP5.json',
       'evidence/wf342/WF342_PROVISIONAL_RATING_TOP5.json']
# Note WF341's source_checkpoint_p3_chance.py already comes from base.
zipname=ART/'WF342_RATING_CRIT_HIT_DEFENSE_WIP_ON_WF341.zip'
with ZipFile(zipname,'w',ZIP_DEFLATED,compresslevel=8) as z:
    for fn in files: z.write(ROOT/fn,arcname=fn)
    z.write(ART/'WF342_VALIDATION.json',arcname='WF342_VALIDATION.json')
    z.write(ART/'WF342_TOP5_RATING_APPROX_REPORT.md',arcname='WF342_TOP5_RATING_APPROX_REPORT.md')
with ZipFile(zipname) as z: assert z.testzip() is None
validation['zip_sha256']=sha256(zipname.read_bytes()).hexdigest()
(ART/'WF342_VALIDATION.json').write_text(json.dumps(validation,indent=2,ensure_ascii=False))
# Recreate ZIP with final validation matching its actual bytes impossible recursive hash inside;
# standalone validation carries ZIP sha, embedded validation omits sha by design.
print(json.dumps({'zip':str(zipname),'bytes':zipname.stat().st_size,'sha':validation['zip_sha256'],
 'report':str(ART/'WF342_TOP5_RATING_APPROX_REPORT.md')},indent=2))
