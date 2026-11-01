#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from src import game_context
from src.class_registry import class_names
from src import state_manager as sm
from src import optimizer_core as opt
from src import pnp_cache
from src.v2 import runtime_state as fast_state
from src.version import SOFTWARE_VERSION
from src.v2.decision_dashboard import build_decision_payload
from src.v2.constrained_routes import analyze_constraint, dual_spec_continuation
from src.v2.talentsforever_compare import (
    compare_to_talentsforever_build, TalentsForeverBuildError,
    TalentsForeverComparisonUnavailable, talentsforever_allocation_at_level,
)
from src.v2.decision_artifacts import frontier_path as decision_frontier_path
from src.v2.item_tools import compare_items, wowhead_upgrade_search
from src.service.publication import resolve_published_path, read_published_class_artifact
from src.service.client import DEFAULT_SERVICE_URL, ServiceClient, ServiceClientError

_SEED_CACHE = {}
_LANDSCAPE_CACHE = {}
_LANDSCAPE_LOCK = threading.Lock()
_SERVICE_SNAPSHOT_LOCK = threading.Lock()
_SERVICE_LAST_GOOD = None
_SERVICE_LAST_GOOD_AT = 0.0
_SERVICE_CONSECUTIVE_FAILURES = 0
_SERVICE_STALE_GRACE_SECONDS = 8.0
_SERVICE_STALE_GRACE_FAILURES = 3

_SERVICE_CLIENT = ServiceClient(os.environ.get("WOW_OPTIMIZER_SERVICE_URL", DEFAULT_SERVICE_URL), timeout=0.75)

_LOCAL_STACK_STATE = Path(os.environ.get("WOW_LOCAL_STACK_STATE", "")) if os.environ.get("WOW_LOCAL_STACK_STATE") else None
_LOCAL_STACK_COMMAND = Path(os.environ.get("WOW_LOCAL_STACK_COMMAND", "")) if os.environ.get("WOW_LOCAL_STACK_COMMAND") else None
_LOCAL_STACK_TOKEN = os.environ.get("WOW_LOCAL_STACK_TOKEN", "")

def local_runtime_snapshot():
    if not (_LOCAL_STACK_STATE and _LOCAL_STACK_TOKEN):
        return {"available": False, "managed": False}
    try:
        obj=json.loads(_LOCAL_STACK_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "managed": True}
    if str(obj.get("token") or "") != _LOCAL_STACK_TOKEN:
        return {"available": False, "managed": True}
    children=obj.get("children") or {}
    return {
        "available": True,
        "managed": True,
        "token": _LOCAL_STACK_TOKEN,
        "listener_url": obj.get("listener_url"),
        "service_url": obj.get("service_url"),
        "children": {k:{"running":bool((v or {}).get("running")),"pid":(v or {}).get("pid")} for k,v in children.items()},
    }

def request_local_runtime(command: str, token: str):
    if not (_LOCAL_STACK_COMMAND and _LOCAL_STACK_TOKEN):
        raise ValueError("listener was not started by service-start.sh")
    if token != _LOCAL_STACK_TOKEN:
        raise ValueError("invalid local stack control token")
    if command not in {"stop-daemon", "stop-all"}:
        raise ValueError("unsupported local stack command")
    tmp=_LOCAL_STACK_COMMAND.with_suffix(_LOCAL_STACK_COMMAND.suffix+".tmp")
    tmp.parent.mkdir(parents=True,exist_ok=True)
    tmp.write_text(json.dumps({"token":_LOCAL_STACK_TOKEN,"command":command,"created_at":time.time()}),encoding="utf-8")
    os.replace(tmp,_LOCAL_STACK_COMMAND)
    return {"accepted": True, "command": command}

def service_snapshot():
    """Read one bounded service read-model snapshot through HTTP only.

    A short control-plane timeout must not make the browser erase durable queue /
    publication state.  Keep one process-local last-known-good snapshot and mark
    transient failures degraded during a small grace window.  A sustained outage
    is still reported offline, but carries the stale snapshot for read-only display.
    """
    global _SERVICE_LAST_GOOD, _SERVICE_LAST_GOOD_AT, _SERVICE_CONSECUTIVE_FAILURES
    try:
        if hasattr(_SERVICE_CLIENT, "status"):
            snap = dict(_SERVICE_CLIENT.status())
            jobs = list(snap.get("jobs") or [])
            active = [j for j in jobs if j.get("state") in {"queued", "running", "paused"}]
            snap.update({
                "available": True,
                "degraded": False,
                "active_jobs": active[:20],
                "active_count": int(snap.get("active_count", len(active))),
                "latest_publication": (snap.get("publications") or [None])[0],
                "service_url": _SERVICE_CLIENT.base_url,
                "item_refresh": (_SERVICE_CLIENT.item_refresh_status() if hasattr(_SERVICE_CLIENT, "item_refresh_status") else None),
            })
            # Optional read-model for source catalogue; do not mark the entire
            # optimizer offline if connected to an older service without it.
            try:
                snap['abilities_capture'] = (_SERVICE_CLIENT.abilities_status()
                                             if hasattr(_SERVICE_CLIENT, 'abilities_status') else None)
            except ServiceClientError as exc:
                snap['abilities_capture'] = {'error': str(exc)}
        else:
            # Compatibility for old injected clients/tests; production uses /api/v1/status.
            health = _SERVICE_CLIENT.health(); jobs = _SERVICE_CLIENT.list_jobs(); pubs = _SERVICE_CLIENT.publications()
            active = [j for j in jobs if j.get("state") in {"queued", "running", "paused"}]
            events = _SERVICE_CLIENT.events(limit=100) if hasattr(_SERVICE_CLIENT, "events") else []
            latest_event = {}
            for event in events: latest_event[event.get("job_id")] = event
            snap = {"available":True,"degraded":False,"health":health,"jobs":jobs[:100],"active_jobs":active[:20],"active_count":len(active),
                    "latest_events":latest_event,"event_cursor":max([int(e.get("seq") or 0) for e in events] or [0]),
                    "publications":pubs[:20],"latest_publication":pubs[0] if pubs else None,"service_url":_SERVICE_CLIENT.base_url}
        now=time.monotonic()
        with _SERVICE_SNAPSHOT_LOCK:
            _SERVICE_LAST_GOOD=dict(snap); _SERVICE_LAST_GOOD_AT=now; _SERVICE_CONSECUTIVE_FAILURES=0
        return snap
    except ServiceClientError as exc:
        now=time.monotonic()
        with _SERVICE_SNAPSHOT_LOCK:
            _SERVICE_CONSECUTIVE_FAILURES += 1
            cached=dict(_SERVICE_LAST_GOOD) if _SERVICE_LAST_GOOD is not None else None
            age=(now-_SERVICE_LAST_GOOD_AT) if _SERVICE_LAST_GOOD_AT else None
            failures=_SERVICE_CONSECUTIVE_FAILURES
        if cached is not None:
            within_grace=(age is not None and age <= _SERVICE_STALE_GRACE_SECONDS and failures <= _SERVICE_STALE_GRACE_FAILURES)
            cached.update({
                "available": bool(within_grace),
                "degraded": True,
                "stale": True,
                "stale_for_seconds": round(float(age or 0.0),3),
                "consecutive_failures": failures,
                "transient_error": str(exc),
                "error": None if within_grace else str(exc),
                "service_url": _SERVICE_CLIENT.base_url,
            })
            return cached
        return {"available": False, "degraded": False, "error": str(exc), "service_url": _SERVICE_CLIENT.base_url}


HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Mage Optimizer</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#111;color:#eee}
header{position:sticky;top:0;background:#181818;padding:16px 22px;border-bottom:1px solid #333;z-index:2}
.grid{display:grid;grid-template-columns:minmax(360px,500px) 1fr;gap:16px;padding:16px}
.panel{background:#191919;border:1px solid #333;border-radius:10px;padding:14px}.panel+.panel{margin-top:16px}
.kpi{font-size:28px;font-weight:700}.muted{color:#aaa}.good{color:#9fe870}.warn{color:#ffcc66}.ref{color:#8ecbff}
.cand,.seedrow{padding:10px;border:1px solid #333;border-radius:8px;margin:8px 0;cursor:pointer}.cand:hover,.cand.sel,.seedrow:hover,.seedrow.sel{border-color:#888;background:#222}
tr.flagged{background:#2a2115}.flag{color:#ffcc66;font-size:12px;margin-top:5px}.rot details{margin-top:4px}.rot summary{cursor:pointer;color:#ddd}.rot ul{margin:6px 0 0 18px;padding:0;color:#bbb}.rot li{margin:2px 0}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;vertical-align:top;padding:7px;border-bottom:1px solid #2f2f2f}
code{white-space:pre-wrap;color:#ddd}.small{font-size:12px}.pill{display:inline-block;border:1px solid #444;border-radius:999px;padding:2px 7px;margin-right:4px}
.sectiontitle{margin-top:12px;font-weight:700}.empty{padding:10px 0;color:#888}.controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
select{background:#111;color:#eee;border:1px solid #555;border-radius:6px;padding:5px 8px;font:inherit} input[type=checkbox]{transform:scale(1.15);accent-color:#9fe870}.watermode{padding:5px 9px;border:1px solid #4b4b4b;border-radius:8px;background:#141414}.seedbest{margin-top:10px;padding:10px;border:1px solid #3c4b33;border-radius:8px;background:#172016}
.seedlist{max-height:420px;overflow:auto}.seedtable{max-height:620px;overflow:auto}.nowrap{white-space:nowrap}.family{font-weight:600}.trees{color:#aaa}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
</style></head>
<body><header><b>Mage optimizer</b> · <b style="color:#9fe870">MC</b> · <a href="/fast" style="color:#8ecbff">Fast</a> · <a href="/decisions" style="color:#9fe870">Decisions</a> <span class="small muted">stochastic search / validation</span> · <a href="/landscape" style="color:#9fe870">3D Search Landscape</a> <span id="updated" class="muted"></span></header>
<div class="grid">
<div>
  <div class="panel">
    <div class="controls"><b>Best build right now</b><label class="watermode"><input id="buyWater" type="checkbox"> Buy water</label><label class="muted">My level <select id="myLevel"></select></label><label class="muted">Max respecs <select id="maxRespecs"></select></label><span id="waterDesc" class="small muted"></span><span id="configState" class="small muted"></span></div>
    <div id="myBest" class="seedbest"><span class="muted">Waiting for per-level seed data…</span></div>
  </div>
  <div class="panel"><div class="muted">Best replayable validated</div><div id="best" class="kpi">—</div><div id="bestmeta" class="small muted"></div></div>
  <div class="panel"><b>Top by school</b><div class="small muted">Best available full-path/validated leader kept separately for each primary school.</div><div id="schoolLeaders"></div></div>
  <div class="panel"><div class="muted">Water sensitivity</div><div id="waterSensitivity" class="small">Waiting for both tracks…</div></div>
  <div class="panel"><div class="muted">Reference benchmark</div><div id="reference" class="kpi ref">—</div><div id="refmeta" class="small muted"></div></div>
  <div class="panel"><b>Runtime</b><div id="runtime" class="small"></div><div id="cacheStats" class="small muted"></div></div>
  <div class="panel"><div class="sectiontitle">Validated candidates (current sim hash)</div><div id="validated"></div><div class="sectiontitle">Stale validated priors</div><div class="small muted">Old code-hash results can guide search but cannot become BEST until replayed under the current simulator hash.</div><div id="staleValidated"></div><div class="sectiontitle">Full-arc search challengers</div><div id="search"></div><div class="sectiontitle">Live search frontier</div><div class="small muted">Partial paths are shown separately; their cumulative hours are not comparable with lvl11–60 totals.</div><div id="frontier"></div></div>
  <div class="panel"><b>Per-level best seeds</b><div class="small muted">Click a level to inspect its full independent seed bank.</div><div id="seedLevels" class="seedlist"></div></div>
</div>
<div>
  <div class="panel"><b id="detailTitle">Candidate replay</b><div id="detailMeta" class="small muted"></div>
  <table><thead><tr><th>Lvl</th><th>Action</th><th>Build after action</th><th>Rotation</th><th>min/100</th><th>XP / mobs</th><th>level h</th><th>avg active DPS</th></tr></thead><tbody id="replay"></tbody></table></div>
  <div class="panel"><b id="seedTitle">Per-level seed bank</b><div id="seedMeta" class="small muted"></div><div id="seedCandidates" class="seedtable"></div></div>
</div>
</div>
<script>
let data=null, selected=null, selectedSeedLevel=null, seedBank=null;
let selectedWater=(localStorage.getItem('mageOptimizerBuyWater')==='false')?'conjured_water':'buy_water';
function esc(x){return String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function hours(x){return x==null?'—':Number(x).toFixed(4)+' h';}
function cid(c){return c?.path_id||c?.id||'';}
function workloadMobs(x){return x?.estimated_workload_mobs??x?.estimated_same_level_mobs??0;}
function min100(x){return x==null?'—':Number(x).toFixed(2)+' min/100';}
function openKeys(root='#replay'){return new Set([...document.querySelectorAll(root+' details[open]')].map(x=>x.dataset.key));}
function rotationHtml(rotation,key,details=[]){
 const lis=(details||[]).map(x=>`<li>${esc(x)}</li>`).join('');
 return `<div class="rot"><details data-key="${esc(key)}"><summary><code>${esc(rotation||'—')}</code></summary>${lis?`<ul>${lis}</ul>`:''}</details></div>`;
}
function restoreOpen(root, keys){document.querySelectorAll(root+' details').forEach(x=>{if(keys.has(x.dataset.key))x.open=true;});}
function treeText(c){const t=c.tree_points||{};return `Frost ${t.frost??0} · Arcane ${t.arcane??0} · Fire ${t.fire??0}`;}
function renderMyBest(){
 const box=document.getElementById('myBest'); const keepOpen=openKeys('#myBest');
 if(!seedBank || !seedBank.candidates || !seedBank.candidates.length){box.innerHTML='<span class="muted">No completed seed bank for this level yet.</span>';return;}
 const c=seedBank.candidates[0], lvl=seedBank.level;
 const xp=c.xp_to_next??seedBank?.meta?.xp_to_next??0, mobs=workloadMobs(c)||workloadMobs(seedBank?.meta), wt=c.objective_weight_per_100??seedBank?.meta?.objective_weight_per_100??0;
 const byWater=data?.seed_levels_by_water||{};
 const buy=(byWater.buy_water||[]).find(x=>Number(x.level)===Number(lvl))?.best;
 const conj=(byWater.conjured_water||[]).find(x=>Number(x.level)===Number(lvl))?.best;
 let localSensitivity='';
 if(buy?.normalized_min_per_100!=null && conj?.normalized_min_per_100!=null){
   const delta=Number(conj.normalized_min_per_100)-Number(buy.normalized_min_per_100);
   localSensitivity=`<div class="small muted" style="margin-top:7px">Local optimum sensitivity: buy ${min100(buy.normalized_min_per_100)} · conjured ${min100(conj.normalized_min_per_100)} · Δ ${delta>=0?'+':''}${delta.toFixed(2)} min/100</div>`;
 }
 const bestId=(data?.best||{}).candidate_id;
 const bestCand=(data?.candidates||[]).find(x=>(x.id===bestId||x.path_id===bestId) && x.validated_hours!=null);
 const pathRow=(bestCand?.replay||[]).find(r=>Number(r.level)===Number(lvl));
 let path='';
 if(pathRow){path=`<div style="margin-top:12px;border-top:1px solid #394238;padding-top:9px"><div class="small muted">Best validated full-path build at lvl ${lvl}</div><div><code>${esc(pathRow.allocation)}</code></div><div style="margin-top:5px">${rotationHtml(pathRow.rotation,`mypath:${lvl}`,pathRow.rotation_details||[])}</div><div class="small muted">${esc(pathRow.action||'')} ${esc(pathRow.detail||'')} · ${min100(pathRow.normalized_min_per_100)}</div></div>`;}
 box.innerHTML=`<div class="small muted">Best fresh-respec seed for this level (local 100-mob objective · ${selectedWater==='buy_water'?'best available water':'self-conjured water only'})</div><div><span class="good"><b>Lvl ${lvl} #1</b> · ${min100(c.normalized_min_per_100)}</span> · <span class="family">${esc(c.family||'')}</span></div>
 <div class="small trees">${esc(treeText(c))}</div><div class="small muted">XP to next ${Number(xp).toLocaleString()} · ≈${Number(mobs).toFixed(1)} L+1/L+2 workload mobs · objective weight ×${Number(wt).toFixed(2)}</div><div style="margin-top:7px"><code>${esc(c.allocation)}</code></div>
 <div style="margin-top:7px">${rotationHtml(c.policy,`mybest:${lvl}:1`,c.rotation_details||[])}</div>${localSensitivity}${path}`;
 restoreOpen('#myBest',keepOpen);
}
function renderDetail(c){
 const keepOpen=openKeys('#replay');
 selected=cid(c); document.querySelectorAll('.cand').forEach(e=>e.classList.toggle('sel',e.dataset.id===selected));
 if(!c){document.getElementById('replay').innerHTML='';document.getElementById('detailMeta').textContent='';return}
 document.getElementById('detailTitle').textContent=`${cid(c)}`;
 const modelDelta=(c.fast_analytic_hours!=null&&c.validated_hours!=null)?` · Fast ${hours(c.fast_analytic_hours)} → MC ${hours(c.validated_hours)} · Δ ${Number(c.fast_vs_mc_delta_hours??(c.validated_hours-c.fast_analytic_hours)).toFixed(4)} h`:'';
 document.getElementById('detailMeta').innerHTML=`validated ${hours(c.validated_hours)} · search ${hours(c.search_hours)}${modelDelta} · respecs ${esc((c.respec_levels||[]).join(', ')||'none')} · ${esc((c.sources||[c.source]).filter(Boolean).join(' + '))}`;
 document.getElementById('replay').innerHTML=(c.replay||[]).map(r=>{
   const details=(r.rotation_details||[]).map(x=>`<li>${esc(x)}</li>`).join('');
   const flags=(r.sanity_flags||[]).map(x=>`<div class="flag">⚠ ${esc(x)}</div>`).join('');
   const key=`${cid(c)}:${r.level}`;
   const rot=`<div class="rot"><details data-key="${esc(key)}"><summary><code>${esc(r.rotation)}</code></summary>${details?`<ul>${details}</ul>`:''}</details>${flags}</div>`;
   return `<tr class="${(r.sanity_flags||[]).length?'flagged':''}"><td>${r.level}</td><td>${esc(r.action)}<br><span class="muted">${esc(r.detail)}</span></td><td><code>${esc(r.allocation)}</code></td><td>${rot}</td><td>${Number(r.normalized_min_per_100||0).toFixed(2)}</td><td class="small nowrap">${Number(r.xp_to_next||0).toLocaleString()}<br>≈${Number(workloadMobs(r)).toFixed(1)}${r.objective_included===false?`<br><span class="muted">search proxy ×${Number(r.search_weight_per_100||0).toFixed(2)}</span>`:''}</td><td>${r.weighted_level_hours==null?'—':Number(r.weighted_level_hours).toFixed(2)}</td><td>${r.avg_active_dps==null?'—':Number(r.avg_active_dps).toFixed(1)}</td></tr>`;
 }).join('');
 restoreOpen('#replay',keepOpen);
}
function card(c,n){
 const partial=!c.full_arc && c.validated_hours==null;
 const score=c.validated_hours!=null?`<span class="good">${hours(c.validated_hours)}</span>`:(partial?`<span class="warn">partial ${hours(c.search_hours)} through L${esc(c.through_level||'?')}</span>`:`<span class="warn">search ${hours(c.search_hours)}</span>`);
 const scope=partial?` · scored L${esc(c.scored_start_level||'?')}→${esc(c.through_level||'?')}`:'';
 return `<div class="cand" data-id="${esc(cid(c))}"><b>#${n}</b> ${score}<br><span class="small">respec ${esc((c.respec_levels||[]).join(', ')||'none')} · ${esc(c.source)}${scope}</span></div>`;
}
function renderSeedLevels(summaries){
 const holder=document.getElementById('seedLevels');
 if(!summaries?.length){holder.innerHTML='<div class="empty">No independent seed banks completed yet.</div>';return;}
 holder.innerHTML=summaries.map(s=>`<div class="seedrow ${Number(s.level)===Number(selectedSeedLevel)?'sel':''}" data-level="${s.level}"><b>Lvl ${s.level}</b> <span class="good">${min100(s.best?.normalized_min_per_100)}</span><br><span class="small muted">${Number(s.best?.xp_to_next||0).toLocaleString()} XP · ≈${Number(workloadMobs(s.best)).toFixed(1)} mobs · ×${Number(s.best?.objective_weight_per_100||0).toFixed(2)}</span><br><span class="small family">${esc(s.best?.family||'')}</span> <span class="small trees">· ${esc(treeText(s.best||{}))}</span><br><span class="small"><code>${esc(s.best?.allocation||'')}</code></span></div>`).join('');
 document.querySelectorAll('.seedrow').forEach(el=>el.onclick=()=>selectSeedLevel(Number(el.dataset.level),true));
}
function renderSeedBank(bank){
 seedBank=bank; const keepOpen=openKeys('#seedCandidates');
 const lvl=bank?.level; document.getElementById('seedTitle').textContent=lvl?`Lvl ${lvl} independent seed bank`:'Per-level seed bank';
 const meta=bank?.meta||{};
 document.getElementById('seedMeta').textContent=lvl?`${(bank.candidates||[]).length} final candidates · ${esc(bank.mode||'')} · seed ${esc(meta.seed??'—')} · stages ${(meta.stages||[]).map(x=>x.mobs+'m').join(' → ')} · ${Number(meta.xp_to_next||0).toLocaleString()} XP ≈ ${Number(workloadMobs(meta)).toFixed(1)} mobs`:'';
 if(!bank?.candidates?.length){document.getElementById('seedCandidates').innerHTML='<div class="empty">No seed bank for this level yet.</div>';renderMyBest();return;}
 document.getElementById('seedCandidates').innerHTML=`<table><thead><tr><th>#</th><th>Score</th><th>Family / trees</th><th>Allocation</th><th>Rotation</th></tr></thead><tbody>${bank.candidates.map(c=>`<tr><td>${c.rank}</td><td class="nowrap">${min100(c.normalized_min_per_100)}</td><td><span class="family">${esc(c.family||'')}</span><br><span class="small trees">${esc(treeText(c))}</span></td><td><code>${esc(c.allocation)}</code></td><td>${rotationHtml(c.policy,`seed:${lvl}:${c.rank}`,c.rotation_details||[])}</td></tr>`).join('')}</tbody></table>`;
 restoreOpen('#seedCandidates',keepOpen); renderMyBest();
}
async function loadSeedBank(level){
 try{const r=await fetch('/api/seeds?water='+encodeURIComponent(selectedWater)+'&level='+encodeURIComponent(level),{cache:'no-store'});if(!r.ok)throw new Error('not found');renderSeedBank(await r.json());}
 catch(e){renderSeedBank({level:level,candidates:[]});}
}
function setLevelSelect(summaries){
 const sel=document.getElementById('myLevel'); const levels=(summaries||[]).map(x=>Number(x.level));
 const old=Number(localStorage.getItem('mageOptimizerMyLevel'));
 if(selectedSeedLevel==null) selectedSeedLevel=(levels.includes(old)?old:(levels.length?Math.max(...levels):11));
 sel.innerHTML=Array.from({length:50},(_,i)=>i+11).map(l=>`<option value="${l}" ${l===selectedSeedLevel?'selected':''}>${l}</option>`).join('');
 sel.onchange=()=>selectSeedLevel(Number(sel.value),true);
}
function selectSeedLevel(level,persist){
 selectedSeedLevel=Number(level); if(persist)localStorage.setItem('mageOptimizerMyLevel',String(selectedSeedLevel));
 document.getElementById('myLevel').value=String(selectedSeedLevel); renderSeedLevels(data?.seed_levels||[]); loadSeedBank(selectedSeedLevel);
}
function syncWaterControl(){
 const cb=document.getElementById('buyWater'); cb.checked=selectedWater==='buy_water';
 document.getElementById('waterDesc').textContent=cb.checked?'Best available/usable water':'Self-conjured water only';
 cb.onchange=()=>{
   selectedWater=cb.checked?'buy_water':'conjured_water';
   localStorage.setItem('mageOptimizerBuyWater',cb.checked?'true':'false');
   selected=null; seedBank=null;
   document.getElementById('myBest').innerHTML='<span class="muted">Loading '+(cb.checked?'buy-water':'conjured-water')+' track…</span>';
   tick();
 };
}
function syncRespecControl(){
 const sel=document.getElementById('maxRespecs');
 if(!sel.options.length) sel.innerHTML=Array.from({length:9},(_,i)=>`<option value="${i}">${i}</option>`).join('');
 const current=Number(data?.user_config?.max_respecs??2);
 if(document.activeElement!==sel) sel.value=String(current);
 document.getElementById('configState').textContent=`current ${current}`;
 sel.onchange=async()=>{
   const v=Number(sel.value); document.getElementById('configState').textContent='saving…';
   try{const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_respecs:v})});
       const x=await r.json(); document.getElementById('configState').textContent=`current ${x.max_respecs} · optimizer will restart reduce`;
   }catch(e){document.getElementById('configState').textContent='save failed';}
 };
}
function renderSchoolLeaders(leaders){
 const holder=document.getElementById('schoolLeaders'); const order=['frost','fire','arcane'];
 const rows=order.map(s=>[s,leaders?.[s]]).filter(x=>x[1]);
 if(!rows.length){holder.innerHTML='<div class="empty">No full-path school leaders yet.</div>';return;}
 holder.innerHTML=rows.map(([school,c])=>{
   const val=c.validated_hours!=null?`<span class="good">${hours(c.validated_hours)}</span>`:`${hours(c.search_hours)} search`;
   const prec=Number(c.search_precision_mobs||0);
   return `<div class="cand" data-id="${esc(cid(c))}"><b>${esc(school[0].toUpperCase()+school.slice(1))}</b> · ${val} ${prec?`<span class="pill">${prec}m search</span>`:''}<br><span class="small muted">${esc(c.family||'')} · respec ${esc((c.respec_levels||[]).join(', ')||'none')}</span></div>`;
 }).join('');
}

function render(d){
 data=d; syncWaterControl(); syncRespecControl(); const s=d.status||{}, b=d.best||{}, ref=d.reference||{};
 document.getElementById('updated').textContent='updated '+new Date((s.updated_at||0)*1000).toLocaleTimeString();
 document.getElementById('best').textContent=hours(b.best_validated_hours); document.getElementById('bestmeta').textContent=(b.source||'')+(b.candidate_id?' · '+b.candidate_id:'');
 document.getElementById('reference').textContent=hours(ref.validated_hours); document.getElementById('refmeta').textContent=ref.note||ref.source||'legacy benchmark only';
 const wb=d.best_by_water||{}, buy=wb.buy_water?.best_validated_hours, conj=wb.conjured_water?.best_validated_hours;
 let sens=`Buy/best-available: <b>${hours(buy)}</b> · self-conjured: <b>${hours(conj)}</b>`;
 if(buy!=null && conj!=null){const delta=Number(conj)-Number(buy),pct=buy?100*delta/Number(buy):0;sens+=` · <span class="${delta>=0?'warn':'good'}">Δ ${delta>=0?'+':''}${delta.toFixed(4)} h (${delta>=0?'+':''}${pct.toFixed(2)}%)</span>`;}
 document.getElementById('waterSensitivity').innerHTML=sens+'<div class="muted" style="margin-top:5px">Each value is independently optimized under its own recovery model; seed allocations cross-pollinate between tracks.</div>';
 document.getElementById('runtime').innerHTML=`<p><span class="pill">${esc(s.state||'unknown')}</span><span class="pill">workers ${esc(s.workers||'—')}</span><span class="pill">computing ${esc(s.water_mode||'—')}</span><span class="pill">XP-weighted 11→60</span><span class="pill">PnP cache</span></p><p>${esc(s.message||'')}</p><p class="muted">viewer ${esc(selectedWater)} · experiment ${esc(s.experiment||'—')} · phase ${esc(s.phase||'—')} · level ${esc(s.level||'—')} · validation ${esc(s.validation_done||0)}/${esc(s.validation_total||'—')}</p>`;
 const pc=d.pnp_cache||{}; const rowtxt=(pc.rows_current==null)?'live stats: no table scan':`current rows ${esc(pc.rows_current)} · stale rows ${esc(pc.rows_stale||0)} · max precision ${esc(pc.max_current_n||0)} mobs`; document.getElementById('cacheStats').innerHTML=`sim hash <code>${esc(pc.sim_code_hash||'—')}</code> · ${rowtxt} · DB ${(Number(pc.db_bytes||0)/1048576).toFixed(1)} MB${Number(pc.wal_bytes||0)?` · WAL ${(Number(pc.wal_bytes)/1048576).toFixed(1)} MB`:''}`;
 const cs=(d.candidates||[]).filter(c=>c.replayable!==false && c.source!=='baseline_100mob_csv');
 renderSchoolLeaders(d.top_by_school||{});
 const curHash=d?.pnp_cache?.sim_code_hash;
 const vals=cs.filter(c=>c.validated_hours!=null && c.sim_code_hash===curHash).sort((a,b)=>a.validated_hours-b.validated_hours);
 const staleVals=cs.filter(c=>c.validated_hours!=null && c.sim_code_hash!==curHash).sort((a,b)=>a.validated_hours-b.validated_hours);
 const sea=cs.filter(c=>c.validated_hours==null && c.full_arc).sort((a,b)=>(a.search_hours??1e99)-(b.search_hours??1e99));
 let frontier=cs.filter(c=>c.validated_hours==null && !c.full_arc);
 const curExp=s.experiment; const currentFrontier=frontier.filter(c=>curExp && String(c.source||'').startsWith(curExp)); if(currentFrontier.length) frontier=currentFrontier;
 const deepest=frontier.length?Math.max(...frontier.map(c=>Number(c.through_level||0))):0; frontier=frontier.filter(c=>Number(c.through_level||0)===deepest).sort((a,b)=>(a.search_hours??1e99)-(b.search_hours??1e99));
 document.getElementById('validated').innerHTML=vals.length?vals.map((c,i)=>card(c,i+1)).join(''):'<div class="empty">No current-hash replayable candidate validated yet.</div>';
 document.getElementById('staleValidated').innerHTML=staleVals.length?staleVals.slice(0,10).map((c,i)=>card(c,i+1)).join(''):'<div class="empty">No stale validated priors.</div>';
 document.getElementById('search').innerHTML=sea.length?sea.map((c,i)=>card(c,i+1)).join(''):'<div class="empty">No full-arc unvalidated challengers.</div>';
 document.getElementById('frontier').innerHTML=frontier.length?frontier.map((c,i)=>card(c,i+1)).join(''):'<div class="empty">No partial frontier right now.</div>';
 document.querySelectorAll('.cand').forEach(el=>el.onclick=()=>renderDetail(cs.find(c=>cid(c)===el.dataset.id)));
 let keep=cs.find(c=>cid(c)===selected)||vals[0]||sea[0]||frontier[0]; renderDetail(keep);
 setLevelSelect(d.seed_levels||[]); renderSeedLevels(d.seed_levels||[]);
 // Always refetch the selected seed bank. This fixes the case where the user
 // selects a level before its file exists, and also keeps a level live while a
 // new epoch overwrites its bank. Open rotations are restored by data-key.
 loadSeedBank(selectedSeedLevel);
}
async function tick(){try{let r=await fetch('/api/state?water='+encodeURIComponent(selectedWater),{cache:'no-store'});render(await r.json())}catch(e){}}
syncWaterControl();tick();setInterval(tick,3000);
</script></body></html>'''


FAST_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Mage Optimizer — Fast</title>
<style>
:root{color-scheme:dark}body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#111;color:#eee}
header{position:sticky;top:0;background:#181818;padding:14px 20px;border-bottom:1px solid #333;z-index:2}a{color:#8ecbff}
.wrap{padding:16px;max-width:1500px;margin:auto}.grid{display:grid;grid-template-columns:360px 1fr;gap:16px}.panel{background:#191919;border:1px solid #333;border-radius:10px;padding:14px;margin-bottom:14px}
.kpi{font-size:26px;font-weight:700}.muted{color:#999}.good{color:#9fe870}.warn{color:#ffcc66}.bad{color:#ff8b8b}.small{font-size:12px}.pill{display:inline-block;border:1px solid #444;border-radius:999px;padding:2px 7px;margin:2px 3px 2px 0}
.tabs{display:flex;gap:8px;margin-bottom:10px}.tabs button{background:#151515;color:#ddd;border:1px solid #444;border-radius:7px;padding:6px 10px;cursor:pointer}.tabs button.sel{border-color:#9fe870;color:#9fe870;background:#172016}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;vertical-align:top;padding:6px 7px;border-bottom:1px solid #2d2d2d}code{white-space:pre-wrap;word-break:break-word;color:#ddd}.scroll{max-height:680px;overflow:auto}.bar{height:8px;background:#292929;border-radius:999px;overflow:hidden;margin-top:7px}.bar>div{height:100%;background:#9fe870}.rowbest{background:#172016}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
</style></head><body>
<header><b>Mage optimizer</b> · <a href="/">MC</a> · <b style="color:#9fe870">Fast</b> · <a href="/decisions">Decisions</a> <span class="small muted">analytic search / exact path DP</span> <span id="updated" class="muted"></span></header>
<div class="wrap"><div class="grid"><div>
<div class="panel"><div class="muted">Fast status</div><div id="status" class="kpi">—</div><div id="message" class="small muted"></div><div class="bar"><div id="progress" style="width:0%"></div></div></div>
<div class="panel"><div class="muted">Best analytic path</div><div id="best" class="kpi">—</div><div id="bestmeta" class="small muted"></div></div>
<div class="panel"><b>Config</b><div id="config" class="small"></div></div>
<div class="panel"><b>Views</b><div id="views"></div></div>
</div><div>
<div class="panel"><div class="tabs" id="tabs"></div><div id="viewSummary"></div></div>
<div class="panel"><b>Respec paths</b><div id="paths"></div></div>
<div class="panel"><b id="levelsTitle">Selected legal path</b><div id="levelsNote" class="small muted">When DP completes this shows the actual legal talent path; while searching it shows independent leaders.</div><div id="levels" class="scroll"></div></div>
</div></div></div>
<script>
let data=null, selectedView=localStorage.getItem('mageFastView')||'hard';
function esc(x){return String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function h(x){return x==null?'—':Number(x).toFixed(3)+' h'}; function sec(x){return x==null?'—':Number(x).toFixed(2)+' s'}; function m100(x){return x==null?'—':Number(x).toFixed(2)+' min/100'};
function tree(c){const t=c?.tree_points||{};return `F ${t.frost??0} · A ${t.arcane??0} · Fi ${t.fire??0}`}
function render(){const d=data||{}, vs=d.views||{}; if(!vs[selectedView]) selectedView=Object.keys(vs)[0]||'hard';
 document.getElementById('updated').textContent=d.updated_at?' · '+new Date(d.updated_at*1000).toLocaleTimeString():'';
 const ph=d.phase||'idle'; document.getElementById('status').textContent=(d.running?'RUNNING · ':'')+ph; document.getElementById('status').className='kpi '+(ph==='error'?'bad':d.running?'warn':'good'); document.getElementById('message').textContent=d.message||'';
 let done=0,total=0; for(const v of Object.values(vs)){done+=Number(v.levels_done||0); total+=Number(v.levels_total||0)} document.getElementById('progress').style.width=(total?Math.min(100,100*done/total):(d.running?5:100))+'%';
 const b=d.best_analytic; document.getElementById('best').textContent=b?h(b.hours):'—'; document.getElementById('bestmeta').textContent=b?`${b.view} · ${b.respecs_used} respec · ${b.final_allocation||''}`:'No completed analytic path yet.';
 const c=d.config||{}; document.getElementById('config').innerHTML=Object.entries(c).map(([k,v])=>`<div><span class="muted">${esc(k)}</span> ${esc(Array.isArray(v)?v.join(', '):v)}</div>`).join('');
 document.getElementById('views').innerHTML=Object.entries(vs).map(([name,v])=>`<div style="margin-top:8px"><b>${esc(name)}</b> · ${esc(v.status||'—')}<br><span class="small muted">${v.levels_done||0}/${v.levels_total||0} levels · search ${sec(v.search_seconds)} · repair ${sec(v.repair_seconds)} · DP ${sec(v.dp_seconds)} · total ${sec(v.total_seconds)}</span></div>`).join('')||'<span class="muted">No views yet.</span>';
 const names=Object.keys(vs); document.getElementById('tabs').innerHTML=names.map(n=>`<button data-v="${esc(n)}" class="${n===selectedView?'sel':''}">${esc(n)}</button>`).join(''); document.querySelectorAll('#tabs button').forEach(x=>x.onclick=()=>{selectedView=x.dataset.v;localStorage.setItem('mageFastView',selectedView);render()});
 const v=vs[selectedView]||{}; const bp=v.best_path; document.getElementById('viewSummary').innerHTML=`<div><b>${esc(selectedView)}</b> · ${esc(v.status||'—')}</div><div class="small muted">${esc(v.message||'')}</div>${bp?`<div style="margin-top:8px"><span class="good"><b>${h(bp.hours)}</b></span> · ${bp.respecs_used} respec · levels through ${bp.resolved_through_level}</div><div class="small"><code>${esc(bp.final_allocation||'')}</code></div><div class="small muted">${esc(bp.final_policy||'')}</div>`:''}`;
 const ps=v.paths||{}; const rows=Object.entries(ps).sort((a,b)=>Number(a[0])-Number(b[0])); const valid=rows.filter(x=>x[1]?.hours!=null); const mn=valid.length?Math.min(...valid.map(x=>Number(x[1].hours))):null; document.getElementById('paths').innerHTML=rows.length?`<table><thead><tr><th>budget</th><th>hours</th><th>Δ best</th><th>used</th><th>respec levels</th><th>final</th></tr></thead><tbody>${rows.map(([r,p])=>p?.hours!=null?`<tr class="${Number(p.hours)===mn?'rowbest':''}"><td>${r}</td><td>${h(p.hours)}</td><td>${mn==null?'—':((Number(p.hours)-mn)*60).toFixed(2)+' min'}</td><td>${p.respecs_used}</td><td>${esc((p.respec_levels||[]).join(', ')||'none')}</td><td><code>${esc(p.final_allocation||'')}</code></td></tr>`:`<tr><td>${r}</td><td colspan="5" class="bad">${esc(p?.error||'unavailable')}</td></tr>`).join('')}</tbody></table>`:'<span class="muted">No solved paths yet.</span>';
 const ls=v.level_summaries||[]; const poolByLevel=Object.fromEntries(ls.map(x=>[Number(x.level),x.pool_size??(x.candidates||[]).length]));
 const pathSteps=(bp&&Array.isArray(bp.steps))?bp.steps:[];
 if(pathSteps.length){
   document.getElementById('levelsTitle').textContent='Selected legal path';
   document.getElementById('levelsNote').textContent='Actual DP-selected path. Every non-respec row is exactly previous build +1 legal talent point.';
   document.getElementById('levels').innerHTML=`<table><thead><tr><th>Lvl</th><th>action</th><th>min/100</th><th>family</th><th>tree</th><th>build</th><th>policy</th><th>pool</th></tr></thead><tbody>${pathSteps.map(q=>`<tr class="${q.kind==='respec'?'rowbest':''}"><td>${q.level}</td><td>${q.kind==='respec'?'<span class="warn">RESPEC</span>':esc(q.talent_added||q.kind||'')}</td><td class="good">${m100(q.min_per_100)}</td><td>${esc(q.family||'')}</td><td>${esc(tree(q))}</td><td><code>${esc(q.allocation||'')}</code></td><td><code>${esc(q.policy||'')}</code></td><td>${poolByLevel[Number(q.level)]??'—'}</td></tr>`).join('')}</tbody></table>`;
 }else{
   document.getElementById('levelsTitle').textContent='Per-level analytic leaders';
   document.getElementById('levelsNote').textContent='Search is not solved yet; these are independent per-level leaders, not a legal progression.';
   document.getElementById('levels').innerHTML=ls.length?`<table><thead><tr><th>Lvl</th><th>min/100</th><th>family</th><th>tree</th><th>build</th><th>policy</th><th>pool</th></tr></thead><tbody>${ls.map(x=>{const q=x.best||{};return `<tr><td>${x.level}</td><td class="good">${m100(q.min_per_100)}</td><td>${esc(q.family||'')}</td><td>${esc(tree(q))}</td><td><code>${esc(q.allocation||'')}</code></td><td><code>${esc(q.policy||'')}</code></td><td>${x.pool_size??(x.candidates||[]).length}</td></tr>`}).join('')}</tbody></table>`:'<span class="muted">Waiting for levels…</span>';
 }
}
async function tick(){try{const r=await fetch('/api/fast',{cache:'no-store'});data=await r.json();render()}catch(e){document.getElementById('message').textContent='Fast snapshot unavailable: '+e}}
tick();setInterval(tick,1500);
</script></body></html>'''


LANDSCAPE_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Mage 3D Talent Path Landscape</title><style>
:root{color-scheme:dark}body{font-family:system-ui;background:#111;color:#eee;margin:0}header{padding:12px 16px;border-bottom:1px solid #333;display:flex;gap:14px;align-items:center;flex-wrap:wrap}header a{color:#9fe870}.wrap{padding:12px}.controls{display:flex;gap:9px;align-items:end;flex-wrap:wrap;margin-bottom:10px}
select,button{background:#151515;color:#eee;border:1px solid #555;border-radius:6px;padding:6px 9px}label{font-size:13px;color:#bbb;display:flex;flex-direction:column;gap:3px}
.stage{display:grid;grid-template-columns:minmax(0,1fr) 370px;gap:12px}.plot{background:#151515;border:1px solid #333;border-radius:10px;overflow:hidden;position:relative;min-height:680px}
canvas{display:block;width:100%;height:680px;touch-action:none;cursor:grab}.side{background:#191919;border:1px solid #333;border-radius:10px;padding:12px;min-width:0}
.muted{color:#999}.small{font-size:12px}.pill{display:inline-block;border:1px solid #444;border-radius:999px;padding:2px 7px;margin:2px}.good{color:#9fe870}.warn{color:#ffcc66}
code{white-space:pre-wrap;word-break:break-word;color:#ddd}.kv{margin:7px 0;border-bottom:1px solid #2c2c2c;padding-bottom:7px}.legend{position:absolute;left:10px;bottom:10px;background:#111d;padding:7px;border-radius:7px;font-size:12px;pointer-events:none}
.tip{position:absolute;display:none;max-width:460px;background:#050505ef;border:1px solid #666;border-radius:7px;padding:8px;font-size:12px;pointer-events:none;z-index:3}
.timeline{font-size:11px;line-height:1.45}.timeline div{padding:2px 0;border-bottom:1px solid #292929}.respec{color:#ffcc66}
@media(max-width:900px){.stage{grid-template-columns:1fr}.plot{min-height:520px}canvas{height:520px}.side{order:-1}}
</style></head><body>
<header><b>3D Talent Path Landscape · lvl10→60</b><a href="/">← live state</a><span id="status" class="small muted">loading…</span></header>
<div class="wrap"><div class="controls">
<label>Water <select id="water"><option value="buy_water">Buy</option><option value="conjured_water">Conjured</option></select></label>
<label>School <select id="school"><option value="all">All</option><option>frost</option><option>fire</option><option>arcane</option></select></label>
<label>Min m <select id="minm"><option selected>1</option><option>2</option><option>4</option><option>8</option><option>16</option><option>32</option><option>64</option><option>100</option></select></label>
<label>Validation <select id="validation"><option value="all">All</option><option value="validated">Validated only</option><option value="search">Search estimates</option></select></label>
<label>Paths <select id="limit"><option>300</option><option>600</option><option selected>1200</option><option>2400</option><option>4000</option></select></label>
<button id="reload" type="button">Reload</button><span class="small muted">one point = one full talent path · drag rotate · wheel zoom · hover/click inspect</span>
</div><div class="stage"><div class="plot"><canvas id="cv"></canvas><div id="tip" class="tip"></div>
<div class="legend">Fill = hours relative to current filters (green best → red slower)<br>Size = √m precision · rim = path school · white ring = selected</div></div>
<div class="side"><div><b>Selection</b></div><div id="detail" class="small muted">Hover or click a path.</div>
<hr style="border:0;border-top:1px solid #333"><div><b>PCA</b></div><div id="pca" class="small muted"></div>
<div class="small muted" style="margin-top:8px">PCA features come from the whole talent trajectory: each talent's average rank in 5-level windows from 10–59. Rotation is shown in details but intentionally excluded from PCA.</div></div></div></div>
<script>
const cv=document.getElementById('cv'),ctx=cv.getContext('2d'),tip=document.getElementById('tip'),statusEl=document.getElementById('status'),detailEl=document.getElementById('detail'),pcaEl=document.getElementById('pca');
const waterEl=document.getElementById('water'),schoolEl=document.getElementById('school'),minmEl=document.getElementById('minm'),validationEl=document.getElementById('validation'),limitEl=document.getElementById('limit'),reloadEl=document.getElementById('reload');
let payload=null,points=[],visible=[],selected=null,yaw=-0.65,pitch=0.42,zoom=1,drag=null,screen=[];
const schoolColors={frost:[90,165,255],fire:[255,116,78],arcane:[190,120,255]};
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function hasNum(v){return v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));}
function parseAlloc(s){const o={};for(const part of String(s||'').split(',')){const q=part.trim();if(!q)continue;const i=q.lastIndexOf('=');if(i<1)continue;const k=q.slice(0,i).trim(),v=Number(q.slice(i+1));if(k&&Number.isFinite(v))o[k]=v;}return o;}
function pathSnapshots(p){const by=new Map((p.steps||[]).map(r=>[Number(r[0]),parseAlloc(r[3])]));let cur={};const out=[];for(let lvl=10;lvl<=59;lvl++){if(by.has(lvl))cur=by.get(lvl);out.push([lvl,cur]);}return out;}
function featureRows(ps){
 const snaps=ps.map(pathSnapshots),tkeys=[...new Set(snaps.flatMap(rows=>rows.flatMap(x=>Object.keys(x[1]))))].sort();
 const bins=[];for(let a=10;a<=55;a+=5)bins.push([a,a+4]);
 const names=[];for(const k of tkeys)for(const [a,b] of bins)names.push(`${k}@${a}-${b}`);
 const X=snaps.map(rows=>{const byLvl=new Map(rows);const vec=[];for(const k of tkeys){for(const [a,b] of bins){let sum=0,n=0;for(let l=a;l<=b;l++){sum+=Number(byLvl.get(l)?.[k]||0);n++;}vec.push(sum/n);}}return vec;});
 return {X,names};
}
function pca3(ps){const {X,names}=featureRows(ps),n=X.length,d=X[0]?.length||0;if(!n||!d)return {coords:ps.map(_=>[0,0,0]),names,ev:[0,0,0]};const mean=Array(d).fill(0),sd=Array(d).fill(0);for(const r of X)for(let j=0;j<d;j++)mean[j]+=r[j];for(let j=0;j<d;j++)mean[j]/=n;for(const r of X)for(let j=0;j<d;j++){const z=r[j]-mean[j];sd[j]+=z*z;}for(let j=0;j<d;j++)sd[j]=Math.sqrt(sd[j]/Math.max(1,n-1))||1;for(const r of X)for(let j=0;j<d;j++)r[j]=(r[j]-mean[j])/sd[j];const comps=[],eig=[];function orth(v){for(const q of comps){let dot=0;for(let j=0;j<d;j++)dot+=v[j]*q[j];for(let j=0;j<d;j++)v[j]-=dot*q[j];}let norm=Math.sqrt(v.reduce((a,x)=>a+x*x,0))||1;for(let j=0;j<d;j++)v[j]/=norm;return v;}function covMul(v){const y=Array(d).fill(0);for(const r of X){let dot=0;for(let j=0;j<d;j++)dot+=r[j]*v[j];for(let j=0;j<d;j++)y[j]+=r[j]*dot;}const den=Math.max(1,n-1);for(let j=0;j<d;j++)y[j]/=den;return y;}for(let c=0;c<3;c++){let v=Array.from({length:d},(_,j)=>Math.sin((j+1)*(c+1)*1.731)+Math.cos((j+3)*(c+2)*.733));v=orth(v);for(let it=0;it<20;it++)v=orth(covMul(v));const av=covMul(v);let lam=0;for(let j=0;j<d;j++)lam+=v[j]*av[j];comps.push(v);eig.push(Math.max(0,lam));}const coords=X.map(r=>comps.map(q=>r.reduce((a,x,j)=>a+x*q[j],0)));const total=Math.max(1,d);return {coords,names,ev:eig.map(x=>x/total)};}
function quality(ps){let best=Infinity;for(const p of ps)if(hasNum(p.hours))best=Math.min(best,Number(p.hours));for(const p of ps)p.q=hasNum(p.hours)&&isFinite(best)?Math.max(0,100*(Number(p.hours)/best-1)):null;}
function qualityColor(p){if(!hasNum(p.q))return 'rgb(125,125,125)';const t=Math.max(0,Math.min(1,Number(p.q)/12));const hue=120*(1-t);return `hsl(${hue.toFixed(1)} 78% 52%)`;}
function schoolColor(p){const c=schoolColors[p.school]||[165,165,165];return `rgb(${c[0]},${c[1]},${c[2]})`;}
function applyFilters(){const mm=Number(minmEl.value),sc=schoolEl.value,vf=validationEl.value;visible=points.filter(p=>p.m>=mm&&(sc==='all'||p.school===sc)&&(vf==='all'||(vf==='validated'&&p.validated)||(vf==='search'&&!p.validated)));quality(visible);draw();statusEl.textContent=`${visible.length.toLocaleString()} shown / ${points.length.toLocaleString()} talent paths · hash ${payload?.sim_code_hash||'—'}`;}
function resize(){const r=cv.getBoundingClientRect(),dpr=Math.min(2,devicePixelRatio||1);cv.width=Math.round(r.width*dpr);cv.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
function project(p,w,h){let [x,y,z]=p.xyz||[0,0,0];const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);const x1=cy*x+sy*z,z1=-sy*x+cy*z,y1=cp*y-sp*z1,z2=sp*y+cp*z1;const scale=Math.min(w,h)*.075*zoom/(1+Math.max(-.75,z2*.035));return [w/2+x1*scale,h/2-y1*scale,z2];}
function draw(){if(!cv.width)return;const r=cv.getBoundingClientRect(),w=r.width,h=r.height;ctx.clearRect(0,0,w,h);ctx.fillStyle='#151515';ctx.fillRect(0,0,w,h);screen=[];const arr=visible.map(p=>({p,s:project(p,w,h)})).sort((a,b)=>a.s[2]-b.s[2]);for(const o of arr){const p=o.p,[x,y]=o.s,rad=2.8+Math.sqrt(Math.max(1,p.m))*.58;ctx.globalAlpha=.48+.48*Math.min(1,p.m/32);ctx.beginPath();ctx.arc(x,y,rad,0,Math.PI*2);ctx.fillStyle=qualityColor(p);ctx.fill();ctx.globalAlpha=.85;ctx.lineWidth=p.validated?2.2:1.2;ctx.strokeStyle=schoolColor(p);ctx.stroke();if(selected===p){ctx.globalAlpha=1;ctx.lineWidth=2.4;ctx.strokeStyle='#fff';ctx.beginPath();ctx.arc(x,y,rad+4,0,Math.PI*2);ctx.stroke();}screen.push({p,x,y,r:Math.max(8,rad+3)});}ctx.globalAlpha=1;}
function nearest(x,y){let best=null,bd=1e99;for(const o of screen){const d=(o.x-x)**2+(o.y-y)**2;if(d<o.r*o.r&&d<bd){bd=d;best=o.p;}}return best;}
function rotationPhases(p){const rows=p.rotations||[];if(!rows.length)return '—';const out=[];let a=null,b=null,last=null;for(const [lv0,rot0] of rows){const lv=Number(lv0),rot=String(rot0||'—');if(last===null){a=b=lv;last=rot;continue;}if(rot===last&&lv===b+1){b=lv;continue;}out.push(`${a}${b>a?'–'+b:''}: ${last}`);a=b=lv;last=rot;}if(last!==null)out.push(`${a}${b>a?'–'+b:''}: ${last}`);return out.join('\n');}
function picksHtml(p){const xs=(p.steps||[]).map(r=>{const lvl=r[0],action=String(r[1]||''),detail=String(r[2]||'');if(action==='respec')return `<div class="respec"><b>L${lvl} RESPEC</b> → ${esc(detail)}</div>`;return `<div>L${lvl} · ${esc(detail||action)}</div>`;});return xs.join('');}
function compactHtml(p){if(!p)return '<span class="muted">Hover or click a path.</span>';const h=hasNum(p.hours)?`${Number(p.hours).toFixed(4)} h`:'hours: —',q=hasNum(p.q)?` · +${Number(p.q).toFixed(2)}% vs best`:'';return `<div><b class="good">${h}</b>${p.validated?' · validated':' · search'}${q}</div><div><span class="pill">${p.m}m</span><span class="pill">${esc(p.school)}</span><span class="pill">${esc(p.family)}</span></div><div class="kv"><b>Final build</b><br><code>${esc(p.final_build||'—')}</code></div><div><b>Respec</b> ${esc((p.respec_levels||[]).join(', ')||'none')}</div>`;}
function detailHtml(p){if(!p)return '<span class="muted">Hover or click a path.</span>';return compactHtml(p)+`<div class="kv"><b>Rotation phases</b><br><code>${esc(rotationPhases(p))}</code></div><div class="kv"><b>Talent path 10→59</b><div class="timeline">${picksHtml(p)}</div></div><div class="kv muted">talent_path_id ${esc(p.talent_path_id||'—')}<br>source ${esc(p.source||'—')}</div>`;}
function hover(p,x,y){if(!p){tip.style.display='none';if(!selected)detailEl.innerHTML=detailHtml(null);return;}tip.innerHTML=compactHtml(p);tip.style.display='block';tip.style.left=Math.max(8,Math.min(x+14,cv.clientWidth-460))+'px';tip.style.top=Math.max(8,y-80)+'px';if(!selected)detailEl.innerHTML=detailHtml(p);}
cv.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,yaw,pitch};cv.setPointerCapture(e.pointerId);cv.style.cursor='grabbing';});
cv.addEventListener('pointermove',e=>{const r=cv.getBoundingClientRect();if(!drag)hover(nearest(e.clientX-r.left,e.clientY-r.top),e.clientX-r.left,e.clientY-r.top);if(drag){yaw=drag.yaw+(e.clientX-drag.x)*.008;pitch=Math.max(-1.3,Math.min(1.3,drag.pitch+(e.clientY-drag.y)*.008));draw();}});
cv.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<5){const r=cv.getBoundingClientRect();selected=nearest(e.clientX-r.left,e.clientY-r.top);detailEl.innerHTML=detailHtml(selected);}drag=null;cv.style.cursor='grab';draw();});
cv.addEventListener('pointerleave',()=>tip.style.display='none');cv.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.35,Math.min(4,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
async function load(){statusEl.textContent='loading full talent paths…';const r=await fetch(`/api/landscape?water=${encodeURIComponent(waterEl.value)}&limit=${limitEl.value}`,{cache:'no-store'});payload=await r.json();points=payload.points||[];if(!points.length){statusEl.textContent='No full 10→60 path observations yet; they appear as outer full-path candidates are produced.';pcaEl.textContent=payload.metadata_note||'';draw();return;}quality(points);statusEl.textContent='computing path PCA…';await new Promise(res=>setTimeout(res,20));const pc=pca3(points);points.forEach((p,i)=>p.xyz=pc.coords[i]);pcaEl.innerHTML=`paths ${points.length} · features ${pc.names.length} · PC1 ${(100*pc.ev[0]).toFixed(1)}% · PC2 ${(100*pc.ev[1]).toFixed(1)}% · PC3 ${(100*pc.ev[2]).toFixed(1)}%<br><span class="muted">${esc(payload.metadata_note||'')}</span>`;selected=null;detailEl.innerHTML=detailHtml(null);applyFilters();resize();}
for(const el of [schoolEl,minmEl,validationEl])el.addEventListener('change',applyFilters);waterEl.addEventListener('change',load);limitEl.addEventListener('change',load);reloadEl.addEventListener('click',load);addEventListener('resize',resize);load().catch(e=>statusEl.textContent='landscape error: '+e);
</script></body></html>'''


DECISIONS_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Forever Leveling Decisions</title><style>
:root{color-scheme:dark;--bg:#0d1015;--panel:#151b25;--line:#2d384b;--muted:#96a0af;--good:#9fe870;--warn:#ffcc66;--bad:#ff8b8b;--link:#8ecbff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#edf0f5;font-family:system-ui,-apple-system,Segoe UI,sans-serif}header{position:sticky;top:0;z-index:5;background:#121722f4;padding:12px 18px;border-bottom:1px solid #2b3444;display:flex;gap:12px;align-items:center;flex-wrap:wrap}a{color:var(--link)}.wrap{max-width:1500px;margin:auto;padding:14px}.muted{color:var(--muted)}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}.small{font-size:12px}.toolbar,.controls{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.toolbar{background:#111722;border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:12px}.toolbar-main{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap}.toolbar-title{font-size:17px;font-weight:780}.toolbar-controls{display:flex;gap:9px;align-items:flex-end;flex-wrap:wrap;margin-top:10px}.toolbar-controls label{display:flex;flex-direction:column;gap:4px;color:var(--muted);font-size:11px}.toolbar-controls select{color:#edf0f5;font-size:13px;min-width:128px}.toolbar label{display:flex;gap:6px;align-items:center}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:13px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:13px}.kpi{font-size:25px;font-weight:750}.pill{display:inline-block;border:1px solid #44516a;border-radius:999px;padding:2px 7px;margin:2px 3px 2px 0;font-size:12px}.pill.opt{border-color:#56743d;color:var(--good)}.pill.warn{border-color:#896f3d;color:#ffd98a}select,input,textarea,button{background:#10151e;color:#edf0f5;border:1px solid #3a465a;border-radius:7px;padding:6px 9px;font:inherit}textarea{width:100%;min-height:70px;resize:vertical}button{cursor:pointer;background:#233049}button:hover{border-color:#6a7b96}.cmp{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px}.cmp-card,.spec-row{border:1px solid #344056;border-radius:9px;padding:10px;background:#111722}.spec-row{display:grid;grid-template-columns:minmax(110px,1fr) minmax(100px,.7fr) minmax(120px,.9fr) minmax(180px,1.5fr);gap:8px;align-items:start;margin-top:7px;cursor:pointer}.spec-row:hover,.spec-row.sel{border-color:#7d91af;background:#182131}.spec-row.spec-head{cursor:default;background:#0d131c;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.03em}.spec-row.spec-head:hover{border-color:#344056;background:#0d131c}.route-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}.route-levels{display:flex;flex-direction:column;gap:8px;margin-top:10px}.level-card{border:1px solid #303c50;border-radius:10px;background:#111722;padding:10px 12px}.level-card.focus{border-color:#8aa45d;box-shadow:0 0 0 1px #4e6035 inset}.level-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}.level-title{font-size:17px;font-weight:750}.level-metrics{text-align:right}.changes{margin:5px 0;color:#c2cad7}.allocation{margin:6px 0;padding:7px 9px;border-left:2px solid #49566d;background:#0f141d;border-radius:4px}.rowline{margin:4px 0}.weights{color:#d7e7c6}.gear-detail{margin-top:7px}.gear-detail summary,.diagnostic summary,details.panel>summary{cursor:pointer}.gear-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:7px}.gear-table th,.gear-table td{text-align:left;vertical-align:top;padding:6px;border-bottom:1px solid #293447}.gear-missing{margin-top:7px}.continuation-result{margin-top:9px;border:1px solid #344056;border-radius:8px;padding:10px}.dual-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px}.decision-context-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:9px}.decision-compare{grid-column:1/-1}.nowrap{white-space:nowrap}.focus-shell{padding:12px}.focus-board{display:grid;grid-template-columns:minmax(300px,.92fr) minmax(520px,1.5fr) minmax(360px,1.05fr);gap:12px;align-items:stretch}.focus-col{display:flex;flex-direction:column;gap:12px;min-width:0}.focus-panel{background:#111722;border:1px solid #344056;border-radius:10px;padding:12px;min-width:0}.focus-panel.grow{flex:1}.focus-title{font-size:18px;font-weight:780}.focus-subtitle{margin-top:2px;color:var(--muted);font-size:12px}.focus-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:10px}.focus-kpi{background:#0d131c;border:1px solid #2c374a;border-radius:8px;padding:11px;text-align:center}.focus-kpi b{font-size:21px;line-height:1.1}.focus-kpi .unit{display:block;margin-top:4px;color:var(--muted);font-size:11px}.talent-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:10px}.talent-tree{border:1px solid #2e394c;border-radius:8px;background:#0e141d;padding:8px;min-height:160px}.talent-tree.active-tree{border-color:#5a5360;background:#111826}.talent-tree h4{margin:0 0 7px;text-transform:capitalize;font-size:13px}.talent-node{display:flex;justify-content:space-between;gap:8px;border-left:3px solid #43526b;background:#151d29;margin:5px 0;padding:6px 7px;border-radius:4px;font-size:12px}.talent-node.active{border-left-color:#e0b84e;background:#1c2230}.entity-label{display:inline-flex;align-items:center;gap:7px;min-width:0}.entity-icon{width:22px;height:22px;object-fit:cover;border:1px solid #58667d;border-radius:4px;background:#0c1118;flex:0 0 auto}.wowhead-entity{color:inherit;text-decoration:none}.wowhead-entity:hover{text-decoration:underline}.wowhead-entity img{border:1px solid #58667d!important;border-radius:4px!important;background:#0c1118!important;margin-right:6px!important;vertical-align:middle!important}.talent-rank{color:#ffd56b;font-weight:700}.talent-summary{width:100%;border-collapse:collapse;font-size:12px;margin-top:10px}.talent-summary th,.talent-summary td{padding:5px 4px;border-bottom:1px solid #293447;text-align:left}.talent-summary th:last-child,.talent-summary td:last-child{text-align:right}.rotation-list{counter-reset:rot;display:flex;flex-direction:column;gap:7px;margin-top:9px}.rotation-step{counter-increment:rot;display:flex;gap:8px;align-items:flex-start;line-height:1.35}.rotation-step:before{content:counter(rot);width:22px;height:22px;border-radius:50%;display:grid;place-items:center;background:#25334a;color:#dce7f7;font-size:11px;flex:0 0 22px}.config-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:11px}.subpanel{background:#0d131c;border:1px solid #2c374a;border-radius:8px;padding:9px}.subpanel-title{font-size:13px;font-weight:750;margin-bottom:7px}.config-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.config-item{border-left:2px solid #45536a;padding-left:7px;min-width:0}.config-item b{display:block;font-size:11px}.config-item span{display:block;color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.timing-bars{display:flex;flex-direction:column;gap:7px}.timing-row{display:grid;grid-template-columns:64px 48px 1fr 38px;gap:6px;align-items:center;font-size:11px}.timing-track{height:9px;border-radius:5px;background:#202a39;overflow:hidden}.timing-fill{height:100%;background:#59a5ff;border-radius:5px}.timing-fill.recovery{background:#65d28c}.timing-fill.travel{background:#e6c34e}.weight-bars{display:flex;flex-direction:column;gap:7px;margin-top:9px}.weight-row{display:grid;grid-template-columns:120px 52px 1fr;gap:7px;align-items:center;font-size:12px}.weight-track{height:10px;border-radius:5px;background:#202a39;overflow:hidden}.weight-fill{height:100%;background:linear-gradient(90deg,#3d8cff,#6bb8ff);border-radius:5px}.focus-gear{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}.focus-gear th,.focus-gear td{padding:6px;border-bottom:1px solid #293447;text-align:left;vertical-align:top}.focus-gear th:first-child,.focus-gear td:first-child{width:66px}.focus-gear .item-name{color:#9dcaff}.coverage-box{margin-top:9px;border:1px solid #3d4a5f;background:#0d131c;border-radius:8px;padding:9px}.focus-empty{color:var(--muted);padding:18px 4px}.route-divider{display:flex;justify-content:space-between;align-items:center;margin:4px 0 8px}.compare-grid{margin-top:0}.compare-grid .panel{margin-bottom:0}.service-grid{display:grid;grid-template-columns:minmax(300px,.8fr) minmax(520px,1.4fr);gap:12px}.job-list{display:flex;flex-direction:column;gap:7px;max-height:330px;overflow:auto}.job-row{border:1px solid #344056;border-radius:8px;padding:8px;background:#0f151e;display:grid;grid-template-columns:minmax(180px,1fr) auto;gap:8px;align-items:center}.job-actions{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}.job-actions button{padding:4px 7px;font-size:11px}.state-running{color:var(--good)}.state-failed,.state-cancelled{color:var(--bad)}.state-paused{color:var(--warn)}.service-history{margin-top:10px;border-top:1px solid #2b3548;padding-top:8px}.pub-row{padding:6px 0;border-bottom:1px solid #273143}.job-meta{margin-top:3px;display:flex;gap:7px;flex-wrap:wrap}.job-progress{margin-top:7px}.progress-track{height:7px;border-radius:5px;background:#202a39;overflow:hidden;min-width:150px}.progress-fill{height:100%;background:#65d28c;border-radius:5px}.stalled{border-color:#8b4a4a!important;background:#211517!important}@media(max-width:1240px){.focus-board{grid-template-columns:minmax(280px,1fr) minmax(460px,1.45fr)}.focus-board>.focus-col:last-child{grid-column:1/-1}.focus-board>.focus-col:last-child .focus-panel{max-width:none}}@media(max-width:900px){.focus-board,.grid2,.cmp,.dual-list,.config-grid{grid-template-columns:1fr}.spec-row{grid-template-columns:1fr 1fr}.level-metrics{text-align:left}.focus-kpis{grid-template-columns:repeat(2,1fr)}.talent-tabs{grid-template-columns:1fr}.talent-tree{min-height:0}.toolbar-main{display:block}.toolbar-controls label{flex:1 1 140px}.toolbar-controls select{width:100%}}
</style>
<script>const whTooltips={colorLinks:false,iconizeLinks:true,renameLinks:false,iconSize:'small'};</script>
<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>
</head><body>
<header><b>Forever leveling decisions</b><span class="small muted">class → spec → route → level; one source of truth</span><span id="serviceStatus" class="small muted" style="margin-left:10px"></span></header>
<div class="wrap">
  <div class="toolbar">
    <div class="toolbar-main">
      <div><div class="toolbar-title">Endpoint route transitions</div><div id="authority" class="small muted"></div></div>
      <div id="focusBadges"></div>
    </div>
    <div class="toolbar-controls">
      <label>Backend<select id="backendPick"></select></label>
      <label>Class<select id="classPick"></select></label>
      <label>Target<select id="targetPick"></select></label>
      <label>Route/spec<select id="routePick"></select></label>
      <label>Inspect level<select id="levelPick"></select></label>
      <button id="validateIceLance" type="button" style="display:none">Validate Ice Lance vs optimum</button>
    </div>
  </div>

  <div class="panel" id="queuedNativePanel">
    <div class="route-head"><div><b>Queued native Decision · explicit inspection</b><div class="small muted">Source-only native job · provider-declared levels · never promotes the Decisions backend</div></div><div class="job-actions"><button type="button" id="enqueueQueuedNative">Queue native Decision</button><button type="button" id="loadQueuedNative">Inspect queued result</button><button type="button" id="retryQueuedNative" style="display:none">Retry status</button></div></div>
    <div id="queuedNativeStatus" class="small muted" style="margin-top:7px">No native job tracked in this tab.</div>
    <div id="queuedNativeResult" class="small muted" style="margin-top:8px">No queued result inspected.</div>
  </div>

  <div class="panel">
    <div class="route-head"><div><b>Backend publication</b><div id="backendPublicationMeta" class="small muted"></div></div></div>
    <div id="backendPublication" style="margin-top:8px"></div>
  </div>

  <details id="servicePanel" class="panel route-product" open>
    <summary><b>Optimizer service</b> <span class="small muted">durable queue · browser is only a client</span></summary>
    <div class="service-grid" style="margin-top:10px">
      <div>
        <div class="controls">
          <label class="small muted">Request <select id="jobAction"><option value="recompute_range">Recompute level range</option><option value="deepen_level">Deepen one level</option><option value="investigate_level">Investigate suspicious level</option></select></label>
          <label class="small muted">Start/level <input id="jobStart" type="number" min="1" max="60" value="11" style="width:72px"></label>
          <label class="small muted">End <input id="jobEnd" type="number" min="1" max="60" value="20" style="width:72px"></label>
          <label class="small muted">Depth <select id="jobDepth"><option value="standard">standard</option><option value="wide">wide</option><option value="deep">deep</option></select></label>
          <label class="small muted">Workers <input id="jobWorkers" type="number" min="1" max="32" value="2" style="width:64px"></label>
          <label class="small muted">Priority <input id="jobPriority" type="number" value="0" style="width:72px"></label>
          <button id="enqueueJob" type="button">Run request</button><button id="clearClone" type="button" style="display:none">Clear clone</button><span id="cloneSource" class="small muted"></span>
          <span id="runtimeControls" style="display:none"><button id="stopWorkers" type="button">Stop optimizer</button><button id="stopAll" type="button" class="danger">Stop all</button></span>
        </div>
        <div class="controls" style="margin-top:8px">
          <label class="small muted">Add item <input id="addItemInput" type="text" placeholder="250531 or Wowhead Forever URL" style="width:330px"></label>
          <button id="addItemButton" type="button">Add item for selected class</button>
          <button id="refreshItemsButton" type="button">Refresh all items</button>
          <span id="addItemResult" class="small muted"></span>
          <span id="refreshItemsResult" class="small muted"></span>
        </div>
        <div class="controls" style="margin-top:9px;border-top:1px solid #344056;padding-top:9px">
          <b class="small">Wowhead · spells &amp; talents</b>
          <button id="refreshAbilitiesButton" type="button">Refresh all 9 class indexes</button>
          <button id="fetchAbilityDetailsButton" type="button">Fetch next 20 tooltips</button>
          <span id="abilitiesCatalogueStatus" class="small muted">Checking catalogue…</span>
        </div>
        <div id="abilitiesRefreshResult" class="small muted" role="status" aria-live="polite" style="margin-top:3px">Index ≠ full talent tree ≠ modeled effects. Captures are staged before replacing the catalogue.</div>
        <div id="serviceMessage" class="small muted" style="margin-top:7px">Service status loading…</div><div id="serviceMeta" class="small muted" style="margin-top:5px"></div><div class="service-history"><div class="route-head"><b class="small">Published results · selected class</b><span id="publicationScope" class="small muted"></span></div><div id="publicationList" class="small" style="margin-top:4px"></div></div>
      </div>
      <div><div class="route-head"><b>Queue / recent jobs</b><button id="refreshJobs" type="button">Refresh</button></div><div id="jobList" class="job-list" style="margin-top:7px"></div><div id="lineagePanel" class="service-history" style="display:none;margin-top:10px"></div><div id="savedStatePanel" class="service-history" style="display:none;margin-top:10px"></div></div>
    </div>
  </details>

  <div class="panel focus-shell route-product">
    <div class="route-head"><div><b id="focusTitle">Selected level</b><div id="focusSubtitle" class="small muted"></div></div></div>
    <div id="focusBoard" class="focus-board" style="margin-top:10px"></div>
  </div>

  <div id="iceLanceValidationPanel" class="panel route-product" style="display:none">
    <div class="route-head"><div><b>Ice Lance validation</b><div class="small muted">Bounded event comparison over the selected level's retained Mage candidate pool.</div></div></div>
    <div id="iceLanceValidation" style="margin-top:8px"></div>
  </div>

  <div class="grid2 compare-grid route-product">
    <div class="panel"><b id="classCompareTitle">Class comparison</b><div class="small warn">Raw throughput is still diagnostic until the class backends share the same combat/gear/pull contract.</div><div id="classCompare" class="cmp" style="margin-top:8px"></div></div>
    <div class="panel"><b id="specCompareTitle">Spec comparison</b><div class="small muted">Regret is cumulative leveling cost versus the unconstrained route. Target-level mobs/h is terminal throughput only, so the cumulative optimum can be slower at the target level. Click a row to inspect it.</div><div id="specCompare"></div></div>
  </div>

  <div id="referencePanel" class="panel route-product">
    <div class="route-head"><div><b>Compare to build</b><div class="small muted">Paste a TalentsForever build URL. Challengers use the canonical class scorer and never become optimizer/search authority.</div></div><label id="storedReferenceLabel" class="small muted">Stored reference <select id="referencePick"></select></label></div>
    <div class="controls" style="margin-top:9px">
      <label class="small muted" style="flex:1;min-width:340px">TalentsForever URL <input id="compareBuildUrl" type="text" placeholder="https://talentsforever.com/druid/60/..." style="width:min(680px,72vw)"></label>
      <label class="small muted">Mode <select id="compareBuildMode"><option value="same_gear">same gear · talent/build only</option><option value="full_decision">own optimized gear</option></select></label>
      <button id="compareBuildRun" type="button">Compare to build</button>
    </div>
    <div id="compareBuildResult" style="margin-top:9px"></div>
    <div id="referenceCoverage" class="small muted" style="margin-top:10px"></div>
    <div id="referenceCompare" style="margin-top:9px"></div>
  </div>

  <div class="panel route-product">
    <div class="route-head"><div><b>Endpoint route transitions</b><div id="routeSummary" class="small muted"></div></div><div id="routeBadges"></div></div>
    <div id="routeLevels" class="route-levels"></div>
  </div>

  <div class="panel route-product">
    <b>Continue from my current talents</b>
    <div class="small muted">Paste your current allocation or a TalentsForever build URL. The listener checks the preserved frontier first; if the exact corridor is missing, you can queue the required canonical calculations.</div>
    <div class="controls" style="margin-top:9px"><label>Current level <select id="currentLevel"></select></label><label>Target <select id="continueTarget"></select></label><button id="continueRun">Find best continuation</button></div>
    <textarea id="currentTalents" placeholder="Paste allocation (talent:rank pairs) or https://talentsforever.com/..."></textarea>
    <div id="continueResult"></div>
  </div>

  <details class="panel route-product"><summary><b>Dual spec</b> <span class="small muted">secondary decision aid</span></summary><div id="dual" class="dual-list" style="margin-top:9px"></div></details>
  <details class="panel diagnostic route-product"><summary><b>Diagnostics / model notes</b></summary><div id="diagnostics" class="small muted" style="margin-top:8px"></div></details>
</div>
<script>
let data=null;
let cloneSourceJob=null;
let processingHistoryExpanded=false;
let legacyPublicationsExpanded=false;
const CURRENT_SOFTWARE_VERSION='__SOFTWARE_VERSION__';
let activeServiceVersion=CURRENT_SOFTWARE_VERSION;
const hiddenProcessingJobs=new Set(JSON.parse(localStorage.getItem('hiddenProcessingJobs')||'[]'));
function persistHiddenProcessingJobs(){localStorage.setItem('hiddenProcessingJobs',JSON.stringify(Array.from(hiddenProcessingJobs).slice(-200)))}
let decisionsPublicationId=null;
let queuedNativeView=null;
let queuedNativeSequence=0;
let nativeQueueJob=null;
let nativeQueueSubmitting=false;
let nativeQueuePolling=false;
const NATIVE_QUEUE_STORAGE_KEY='foreverNativeQueueJob_'+CURRENT_SOFTWARE_VERSION;
const NATIVE_QUEUE_AS_OF='2026-10-08';
function nativeQueueMatchesSelection(){return !!nativeQueueJob&&nativeQueueJob.cls===state.cls&&nativeQueueJob.level===Number(state.level)}
function nativeQueueRequestMatches(job,cls,level){
 const r=job?.request||{};
 return !!job?.id && /^[a-f0-9]{32}$/.test(job.id) && r.ruleset==='forever' && r.class_name===cls &&
 Number(r.start_level)===level && Number(r.end_level)===level && r.objective==='endpoint' &&
 r.endpoint_mode==='generic_decision' && r.forever_build_as_of===NATIVE_QUEUE_AS_OF &&
 r.source_snapshot==='current' && r.engine_semantic_hash==='current' &&
 r.policy_space_version==='current' && Array.isArray(r.validation_modes) && !r.validation_modes.length &&
 Object.keys(r.config||{}).every(k=>k==='producer_version') &&
 r.config?.producer_version===CURRENT_SOFTWARE_VERSION;
}
function saveNativeQueueJob(){
 try{if(nativeQueueJob)sessionStorage.setItem(NATIVE_QUEUE_STORAGE_KEY,JSON.stringify({id:nativeQueueJob.id,cls:nativeQueueJob.cls,level:nativeQueueJob.level}));
 else sessionStorage.removeItem(NATIVE_QUEUE_STORAGE_KEY)}catch(e){}
}
function restoreNativeQueueJob(){
 try{const raw=JSON.parse(sessionStorage.getItem(NATIVE_QUEUE_STORAGE_KEY)||'null');
 if(raw && /^[a-f0-9]{32}$/.test(raw.id) && (classMeta(raw.cls).queued_native_decision_levels||[]).includes(raw.level)){
  nativeQueueJob={id:raw.id,cls:raw.cls,level:raw.level,state:'checking',failures:0,error:''};
 }}catch(e){};
 renderQueuedNativeView();
}

let lastBuildComparison=null;
let lastContinuation=null;
let servicePollInFlight=false;
let lastServiceSnapshot=null;
// G49a: old implicit 'legacy' storage must not pin future capability defaults.
// Prior generic/compare choices were necessarily explicit in the old UI.
const savedDecisionBackend=localStorage.getItem('foreverDecisionBackend');
let backendExplicit=localStorage.getItem('foreverDecisionBackendExplicit')==='1'||
  (localStorage.getItem('foreverDecisionBackendExplicit')===null&&['generic','compare'].includes(savedDecisionBackend));
// Persist auto vs manual independently of the last displayed backend, or an
// automatic generic response would become a pinned manual choice on refresh.
localStorage.setItem('foreverDecisionBackendExplicit',backendExplicit?'1':'0');
let state={backend:savedDecisionBackend||'legacy',cls:localStorage.getItem('foreverDecisionClass')||'paladin',target:localStorage.getItem('foreverDecisionTarget')||'20',route:localStorage.getItem('foreverDecisionRoute')||'unconstrained',level:Number(localStorage.getItem('foreverDecisionLevel')||20)};
let currentRows=new Map();
const $=id=>document.getElementById(id);
function classMeta(cls){return data?.class_metadata?.[cls]||{}}
function classColor(cls){return classMeta(cls).accent||'#ddd'}
function classLabel(cls){const m=classMeta(cls),proof=m.proof_only?' · proof':'';return `${m.display_name||cls}${proof}`}
function esc(x){return String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function mph(x){return x==null?'—':Number(x).toFixed(1)+' mobs/h'}
function sec(x){return x==null?'—':Number(x).toFixed(2)+'s'}
function badge(x,c=''){return `<span class="pill ${c}">${esc(x)}</span>`}
function timingSummary(b){const kill=b?.kill_seconds_per_mob,reco=b?.recovery_seconds_per_mob,travel=b?.travel_seconds_per_mob,total=b?.seconds_per_mob;if(kill==null&&reco==null&&total==null)return 'timing —';const parts=[];if(kill!=null)parts.push(`kill ${sec(kill)}`);if(reco!=null)parts.push(`recovery ${sec(reco)}`);if(travel!=null&&Number(travel)>1e-9)parts.push(`travel ${sec(travel)}`);return total!=null?`mob ${sec(total)}${parts.length?' = '+parts.join(' + '):''}`:parts.join(' + ')}
function recoveryCycleSummary(row){const pulls=Number(row?.pulls_per_recovery),event=Number(row?.recovery_event_s),amort=Number(row?.recovery_seconds_per_mob),trigger=row?.recovery_trigger,method=row?.recovery_method,energy=row?.cat_chain_model==='stateful_energy_between_mobs_v1';if(!Number.isFinite(pulls)&&!Number.isFinite(event)&&!trigger&&!energy)return '';const bits=[];if(Number.isFinite(pulls)&&pulls>0)bits.push(`continue ${Math.max(1,Math.round(pulls))} pull${Math.round(pulls)===1?'':'s'} per recovery cycle`);if(trigger)bits.push(String(trigger).replaceAll('_',' '));if(Number.isFinite(event))bits.push(`full event ${sec(event)}`);if(Number.isFinite(amort))bits.push(`amortized ${sec(amort)}/mob`);if(method)bits.push(String(method).replaceAll('_',' '));if(energy)bits.push('Cat Energy carries between mobs + travel regen; combo points reset per target');return bits.join(' · ')}
function setOptions(el,items,value){el.innerHTML=items.map(x=>`<option value="${esc(x.value)}" ${String(x.value)===String(value)?'selected':''}>${esc(x.label)}</option>`).join('')}
function fmtNum(x,n=2){const v=Number(x);return Number.isFinite(v)?v.toFixed(n).replace(/\.?0+$/,''):'—'}
function statWeightAvailability(row){
  const sw=row?.stat_weights||row?.details?.stat_weights||{},st=sw.stats||{},groups={not_probeable:[],not_modeled:[]};
  for(const [k,v] of Object.entries(st)){const status=String(v?.status||'measured');if(groups[status])groups[status].push(k)}
  const parts=[];
  if(groups.not_probeable.length)parts.push(`not probeable: ${groups.not_probeable.join(', ')}`);
  if(groups.not_modeled.length)parts.push(`not modeled: ${groups.not_modeled.join(', ')}`);
  return parts.join(' · ');
}
function statWeightSummary(row){
  const sw=row?.stat_weights||row?.details?.stat_weights||{};
  if(!sw||(!sw.stats&&!sw.weights&&!sw.curve_sensitivity)){const err=row?.stat_weights_error||row?.details?.stat_weights_error;return err?`contract failure · ${err}`:'contract failure';}
  const availability=statWeightAvailability(row),suffix=availability?` · ${availability}`:'';
  if(sw.stats){
    const st=sw.stats||{},eq=sw.equal_item_budget||{};
    if(eq.rank?.length){
      const xs=eq.rank.map(k=>[k,Number(st[k]?.seconds_saved_per_100_per_equal_budget),Number(st[k]?.equal_budget_normalized_to_reference)]).filter(([k,v])=>st[k]?.status!=='not_modeled'&&st[k]?.status!=='not_probeable'&&Number.isFinite(v)&&v>0).slice(0,6);
      if(xs.length){
        const budgeted=new Set(eq.rank);
        const rawOnly=Object.entries(st).map(([k,v])=>[k,Number(v?.seconds_saved_per_100_per_point),v?.status||'measured']).filter(([k,v,status])=>status==='measured'&&!budgeted.has(k)&&Number.isFinite(v)&&v>=0).sort((a,b)=>b[1]-a[1]).slice(0,3);
        const weapon=sw.equal_item_budget_domains?.weapon_slot||{},wx=(weapon.rank||[]).map(k=>[k,Number(st[k]?.equal_budget_domains?.weapon_slot?.seconds_saved_per_100_per_equal_budget),Number(st[k]?.equal_budget_domains?.weapon_slot?.equal_budget_normalized_to_reference)]).filter(([k,v])=>Number.isFinite(v)&&v>0).slice(0,5);
        const weaponText=wx.length?` · weapon-slot ${weapon.weapon_hands===2?'2H':(weapon.weapon_hands===1?'1H':'')} · ${wx.map(([k,v,n])=>`${k} ${v.toFixed(2)}s/100/WB${Number.isFinite(n)?` (${n.toFixed(2)}×${weapon.reference_stat||'ref'})`:''}`).join(' · ')}`:'';
        return `${sw.analytical?'analytic · ':''}equal-budget · ${xs.map(([k,v,n])=>`${k} ${v.toFixed(2)}s/100/B${Number.isFinite(n)?` (${n.toFixed(2)}×${eq.reference_stat||'ref'})`:''}`).join(' · ')}${weaponText}${rawOnly.length?` · raw-only ${rawOnly.map(([k,v])=>`${k} ${v.toFixed(2)}s/100/pt`).join(' · ')}`:''}${suffix}`;
      }
    }
    const ref=sw.reference_stat;
    const xs=Object.entries(st).map(([k,v])=>[k,Number(v?.seconds_saved_per_100_per_point),Number(v?.normalized_to_reference??v?.normalized_to_spell_power),v?.status||'measured']).filter(([,v,,status])=>status==='measured'&&Number.isFinite(v)&&v>0).sort((a,b)=>b[1]-a[1]).slice(0,8);
    if(xs.length)return `${sw.analytical?'analytic · ':''}${xs.map(([k,v,n])=>`${k} ${v.toFixed(2)}s/100/pt${Number.isFinite(n)?` (${n.toFixed(2)}×${ref||'ref'})`:''}`).join(' · ')}${suffix}`;
    const sp=st.spell_power||{},spi=st.spirit||{},legacy=[];
    if(Number.isFinite(Number(sp.points_per_one_intellect)))legacy.push(`1 INT ≈ ${Number(sp.points_per_one_intellect).toFixed(2)} SP`);
    if(Number.isFinite(Number(spi.points_per_one_intellect)))legacy.push(`${Number(spi.points_per_one_intellect).toFixed(2)} SPI`);
    if(legacy.length)return `${sw.analytical?'analytic · ':''}${legacy.join(' ≈ ')}${suffix}`;
    const measuredZero=Object.entries(st).filter(([,v])=>(v?.status||'measured')==='measured'&&Number(v?.seconds_saved_per_100_per_point)===0).map(([k])=>k);
    if(measuredZero.length)return `${sw.analytical?'analytic · ':''}measured zero: ${measuredZero.join(', ')}${suffix}`;
    if(availability)return `${sw.analytical?'analytic · ':''}${availability}`;
  }
  const raw=sw.weights||sw.curve_sensitivity||{};
  const xs=Object.entries(raw).map(([k,v])=>[k,Number(typeof v==='object'?(v.relative_percent_per_unit??v.relative_percent):v)]).filter(([,v])=>Number.isFinite(v)&&v>0).sort((a,b)=>b[1]-a[1]).slice(0,8);
  return xs.length?xs.map(([k,v])=>`${k} ${v.toFixed(3)}`).join(' · '):'—';
}
function gearStatSummary(x){if(x?.stat_summary)return esc(x.stat_summary);const fields=[['strength','Str'],['agility','Agi'],['stamina','Sta'],['intellect','Int'],['spirit','Spi'],['mp5','mp5'],['spell_power','SP'],['healing','Heal'],['defense','Def'],['armor','armor'],['block_value','block'],['spell_hit','hit%'],['spell_crit','crit%'],['wand_dps','wand dps'],['weapon_dps','weapon dps'],['weapon_speed','speed']];const parts=fields.filter(([k])=>Math.abs(Number(x?.[k]||0))>1e-12).map(([k,label])=>`${label} ${fmtNum(x[k])}`);return esc(parts.join(' · ')||'no numeric contribution')}
const slotOrder=['head','neck','shoulder','back','chest','wrist','hands','waist','legs','feet','ring1','ring2','trinket1','trinket2','relic','ranged','weapon','offhand','wand'];
function gearCoverage(g){const slots=g?.slots||{},auth=g?.catalogue_coverage;if(auth){const used=slotOrder.filter(s=>slots[s]),byStatus=st=>slotOrder.filter(s=>!slots[s]&&auth?.[s]?.status===st);return {used,catalogueOnly:byStatus('available'),missing:[...byStatus('catalogue_gap'),...byStatus('query_gap')],blocked:byStatus('setup_blocked'),proficiency:byStatus('proficiency_blocked'),noItem:byStatus('no_item')}}const counts=g?.catalogue_candidate_counts||{},blocked=new Set(g?.blocked_slots||[]);if(slots.ranged)blocked.add('wand');if(slots.wand)blocked.add('ranged');const used=slotOrder.filter(s=>slots[s]),catalogueOnly=slotOrder.filter(s=>!slots[s]&&!blocked.has(s)&&Number(counts[s]||0)>0),missing=slotOrder.filter(s=>!slots[s]&&!blocked.has(s)&&Number(counts[s]||0)<=0);return {used,catalogueOnly,missing,blocked:[...blocked],proficiency:[],noItem:[]}}
function gearDetailsHtml(row){const g=row?.gear_stats;if(!g)return '<div class="muted">gear snapshot unavailable</div>';const cov=gearCoverage(g),slots=g.slots||{};const itemRows=cov.used.map(slot=>{const x=slots[slot];return `<tr><td class="nowrap">${esc(slot)}</td><td><b>${entityLabel(x.name||'—',x.icon,'item-icon')}</b><div class="muted">${esc(x.source_type||'')}${x.source?` · ${esc(x.source)}`:''}${x.effective_level!=null?` · available L${esc(x.effective_level)}`:''}</div></td><td><b>${gearStatSummary(x)}</b></td></tr>`}).join('');let audit='';if(g.reconciliation_ok!=null){const agg=o=>{const fields=[['strength','Str'],['agility','Agi'],['stamina','Sta'],['intellect','Int'],['spirit','Spi'],['mp5','mp5'],['spell_power','SP'],['healing','Heal'],['defense','Def'],['body_armor','body armor'],['shield_armor','shield armor'],['block_value','block'],['weapon_dps','weapon dps']];return fields.filter(([k])=>Math.abs(Number(o?.[k]||0))>1e-12).map(([k,n])=>`${n} ${fmtNum(o[k])}`).join(' · ')||'0'};audit=`<details class="diagnostic small" style="margin-top:7px"><summary>gear diagnostics</summary><div><b>combat aggregate</b> ${esc(agg(g.combat_totals))}<br><b>displayed slot sum</b> ${esc(agg(g.slot_totals))}<br>reconciliation <span class="${g.reconciliation_ok?'good':'bad'}">${g.reconciliation_ok?'OK':'FAILED'}</span>${g.reconciliation_max_abs_delta!=null?` · max |Δ| ${Number(g.reconciliation_max_abs_delta).toExponential(2)}`:''}<br>${esc(g.gear_selection_method||'')} ${g.inventory_continuity===false?'· rerolled independently each level':''}</div></details>`;}return `${itemRows?`<table class="gear-table"><thead><tr><th>slot</th><th>item</th><th>explicit stats used by model</th></tr></thead><tbody>${itemRows}</tbody></table>`:'<div class="muted">No named items in this snapshot.</div>'}${cov.catalogueOnly.length?`<div class="small muted"><b>Catalogue candidates available:</b> ${cov.catalogueOnly.map(s=>`${esc(s)} (${Number(g.catalogue_candidate_counts?.[s]||0)})`).join(', ')}</div>`:''}${cov.missing.length?`<div class="gear-missing small warn"><b>Missing catalogue/query coverage:</b> ${esc(cov.missing.join(', '))}</div>`:''}${cov.noItem?.length?`<div class="small muted">No canonical item: ${esc(cov.noItem.join(', '))}</div>`:''}${cov.proficiency?.length?`<div class="small muted">Unavailable by proficiency/slot: ${esc(cov.proficiency.join(', '))}</div>`:''}${cov.blocked.length?`<div class="small muted">Blocked by hand setup: ${esc(cov.blocked.join(', '))}</div>`:''}${audit}`}
function classes(){if(!backendExplicit&&Array.isArray(data?.backend_selection?.selectable_classes))return data.backend_selection.selectable_classes;if(data?.active_backend==='generic')return Object.keys(data?.class_metadata||{});return [...new Set([...Object.keys(data?.class_metadata||{}),...Object.keys(data?.endpoint_paths||{}),...Object.keys(data?.spec_matrix||{}),...(data?.cards||[]).map(x=>x.class)])]}
function targetMeta(cls,target){return data?.endpoint_paths?.[cls]?.targets?.[String(target)]||{}}
function matrixFor(cls,target,route){const c=data?.spec_matrix?.[cls]||{};if(c.matrices)return c.matrices[`${Number(target)}:${route}`]||null;if(c.rows&&String(c.route)===String(route)&&Number(c.target_level)===Number(target))return c;return null}
function routeRowsFor(cls,target,route){const canonicalRoute=data?.route_rows?.[cls]?.[String(target)]?.routes?.[route];if(canonicalRoute)return canonicalRoute.status==='available'?(canonicalRoute.rows||[]):[];const mat=matrixFor(cls,target,route),matrixRows=mat?.status==='available'?(mat.rows||[]):[];if(matrixRows.length)return matrixRows;const endpoint=targetMeta(cls,target)?.routes?.[route],steps=endpoint?.path?.steps||[],byLevel=new Map();for(const x of steps)byLevel.set(Number(x.level),{...x});return [...byLevel.entries()].sort((a,b)=>a[0]-b[0]).map(([level,row])=>({...row,level}))}
function hasStatWeights(row){const sw=row?.stat_weights||row?.details?.stat_weights||{};return !!(sw&&((sw.stats&&Object.keys(sw.stats).length)||(sw.weights&&Object.keys(sw.weights).length)||(sw.curve_sensitivity&&Object.keys(sw.curve_sensitivity).length)))}
function routesFor(cls,target){const m=targetMeta(cls,target),artifact=Object.keys(m.routes||{}),declared=classMeta(cls).declared_routes||[],c=data?.spec_matrix?.[cls]?.matrices||{},matrix=Object.values(c).filter(x=>Number(x.target_level)===Number(target)).map(x=>x.route),canonical=data?.route_rows?.[cls]?.[String(target)]?.routes||{},names=[];const per=(data?.per_level_rows?.[cls]||[]).filter(r=>Number(r.level)<=Number(target));if(per.length&&per.every(hasStatWeights))names.push('per_level_best');names.push('unconstrained',...(declared.length?declared:[...artifact,...matrix]));return [...new Set(names.filter(Boolean))].filter(name=>{if(name==='per_level_best')return true;const route=canonical?.[name]||{},rows=route?.rows||[];return route?.status==='available'&&rows.length&&rows.every(hasStatWeights)})}
function targetsFor(cls){const a=Object.entries(data?.endpoint_paths?.[cls]?.targets||{}).filter(([,v])=>v.status==='available').map(([k])=>Number(k));const b=Object.values(data?.spec_matrix?.[cls]?.matrices||{}).filter(x=>x.status==='available').map(x=>Number(x.target_level));const per=(data?.per_level_rows?.[cls]||[]).map(r=>Number(r.level)).filter(Number.isFinite);const c=per.length?[Math.max(...per)]:[];return [...new Set([...a,...b,...c])].sort((x,y)=>x-y)}
function bestMatrixRow(cls,level){const mats=Object.values(data?.spec_matrix?.[cls]?.matrices||{}).filter(m=>m.status==='available'&&m.route==='unconstrained'&&(m.rows||[]).some(r=>Number(r.level)===Number(level)));mats.sort((a,b)=>{const aa=Number(a.target_level)>=Number(level)?0:1,bb=Number(b.target_level)>=Number(level)?0:1;return aa-bb||Math.abs(Number(a.target_level)-Number(level))-Math.abs(Number(b.target_level)-Number(level))});const m=mats[0];return m?(m.rows||[]).find(r=>Number(r.level)===Number(level)):null}
function perLevelRow(cls,level){return (data?.per_level_rows?.[cls]||[]).find(r=>Number(r.level)===Number(level))||null}
function syncState(opts={}){const backendRows=Array.isArray(data?.backends)?data.backends:[],active=String(data?.active_backend||state.backend||'legacy');state.backend=backendRows.some(x=>String(x.id)===active)?active:(backendRows[0]?.id||active);setOptions($('backendPick'),[{value:'auto',label:`auto · ${state.backend} (capability-gated)`},...backendRows.map(x=>({value:x.id,label:`${x.id}${x.status&&x.status!=='available'?' · '+x.status:''}`}))],backendExplicit?state.backend:'auto');localStorage.setItem('foreverDecisionBackend',state.backend);const cs=classes();if(!cs.includes(state.cls))state.cls=cs.includes('paladin')?'paladin':cs[0];const routeProduct=data?.product_surface?.route_navigation!==false&&!(state.backend==='generic'&&!targetsFor(state.cls).length);if(!routeProduct){
  // G48d: no native route does NOT mean no source-IR level navigation.
  // Source-only level changes fetch a fresh DecisionRecord from the service;
  // route levels are local focus on separately scored native decisions.
  state.target='';state.route='';
  const genericSourceOnly=state.backend==='generic';
  const bounds=genericSourceOnly?(classMeta(state.cls).source_ir_level_bounds||{}):{};
  const min=Number(bounds.min),max=Number(bounds.max);
  const validBounds=bounds.min!=null&&bounds.max!=null&&Number.isInteger(min)&&Number.isInteger(max)&&min>=1&&max>=min&&max-min<=59;
  const sourceLevels=validBounds?Array.from({length:max-min+1},(_,i)=>min+i):[];
  const publishedLevel=Number(data?.selected_level??20);
  state.level=publishedLevel; // authoritative: never display L20 with a cached L10 record
  const options=sourceLevels.length?sourceLevels:[state.level];
  if(!options.includes(state.level))options.push(state.level);
  setOptions($('classPick'),cs.map(x=>({value:x,label:classLabel(x)})),state.cls);
  setOptions($('targetPick'),[],state.target);
  setOptions($('routePick'),[],state.route);
  setOptions($('levelPick'),options.map(x=>({value:x,label:`L${x}${genericSourceOnly?' · source IR only':''}`})),state.level);
  setOptions($('currentLevel'),[],state.level);
  setOptions($('continueTarget'),[],state.target);
  $('targetPick').disabled=true;$('routePick').disabled=true;
  $('levelPick').disabled=!genericSourceOnly||sourceLevels.length<2;
  localStorage.setItem('foreverDecisionClass',state.cls);
  localStorage.setItem('foreverDecisionLevel',String(state.level));
  return
} $('targetPick').disabled=false;$('routePick').disabled=false;$('levelPick').disabled=false;let ts=targetsFor(state.cls);if(!ts.length&&!opts.allowEmptyClass){const ready=cs.filter(cls=>targetsFor(cls).length);if(ready.length){state.cls=ready[0];state.target='';state.route='';state.level=NaN;ts=targetsFor(state.cls)}}if(!ts.map(String).includes(String(state.target)))state.target=String(ts.at(-1)??'');const rs=routesFor(state.cls,state.target);if(!rs.includes(state.route))state.route=rs.includes('unconstrained')?'unconstrained':(rs[0]||'');let levels=[];if(state.route==='per_level_best'){levels=(data?.per_level_rows?.[state.cls]||[]).filter(r=>Number(r.level)<=Number(state.target)).map(r=>Number(r.level))}else{const canonical=data?.route_rows?.[state.cls]?.[String(state.target)]?.routes?.[state.route]?.rows||[],mat=matrixFor(state.cls,state.target,state.route),route=targetMeta(state.cls,state.target)?.routes?.[state.route];levels=[...canonical.map(x=>Number(x.level)),...(mat?.rows||[]).map(x=>Number(x.level)),...(route?.path?.steps||[]).map(x=>Number(x.level))]}levels=[...new Set(levels.filter(Number.isFinite))].sort((a,b)=>a-b);if(!levels.length&&Number(state.target))levels=[Number(state.target)];if(levels.length&&!levels.includes(Number(state.level)))state.level=levels.at(-1);setOptions($('classPick'),cs.map(x=>({value:x,label:classLabel(x)})),state.cls);setOptions($('targetPick'),ts.map(x=>({value:x,label:`target L${x}`})),state.target);setOptions($('routePick'),rs.map(x=>({value:x,label:x==='unconstrained'?'unconstrained · cumulative optimum':(x==='per_level_best'?'per-level fastest · respec as needed (~1s)':routeLabel(state.cls,x))})),state.route);setOptions($('levelPick'),levels.map(x=>({value:x,label:`L${x}`})),state.level);setOptions($('currentLevel'),levels.map(x=>({value:x,label:`L${x}`})),state.level);setOptions($('continueTarget'),ts.filter(x=>x>=Number(state.level)).map(x=>({value:x,label:`target L${x}`})),state.target);localStorage.setItem('foreverDecisionClass',state.cls);localStorage.setItem('foreverDecisionTarget',state.target);localStorage.setItem('foreverDecisionRoute',state.route);localStorage.setItem('foreverDecisionLevel',String(state.level))}
function renderClassCompare(){const lvl=Number(state.level);$('classCompareTitle').textContent=`Class comparison · L${lvl} · per-level fastest`;$('classCompare').innerHTML=classes().map(cls=>{const r=perLevelRow(cls,lvl);return `<div class="cmp-card"><b style="color:${classColor(cls)}">${esc(classLabel(cls))}</b>${r?`<div class="kpi">${mph(r.mobs_per_hour)}</div><div class="small">${badge(r.talent_family||'—')} ${badge(r.combat_profile||'—')} ${badge('pull '+(r.pull_size??'—'))}</div><div class="small muted">${esc(timingSummary(r))}</div>`:`<div class="muted" style="margin-top:6px">No per-level winner at L${lvl}.</div>`}</div>`}).join('')}
function renderSpecCompare(){const target=state.target,meta=targetMeta(state.cls,target),reg=data?.spec_regret?.[state.cls]?.targets?.[String(target)]?.routes||{},routes=meta.routes||{},canonical=data?.route_rows?.[state.cls]?.[String(target)]?.routes||{},names=routesFor(state.cls,target).filter(x=>x!=='per_level_best');$('specCompareTitle').textContent=`Spec comparison · ${state.cls} → L${target}`;const terminalRows=names.map(name=>{const rows=routeRowsFor(state.cls,target,name),path=routes?.[name]?.path||{},last=rows.find(r=>Number(r.level)===Number(target))||rows.at(-1)||null;return [name,last||path]}),terminalBest=Math.max(0,...terminalRows.map(([,r])=>Number(r?.mobs_per_hour||0)));$('specCompare').innerHTML=names.length?`<div class="spec-row spec-head"><div>Route</div><div>Constrained regret</div><div>L${target} terminal throughput</div><div>Scored profile</div></div>`+names.map(name=>{const route=routes[name]||{},rr=reg[name]||{},cr=canonical[name]||{},rows=routeRowsFor(state.cls,target,name),path=route.path||{},terminal=rows.find(r=>Number(r.level)===Number(target))||rows.at(-1)||path,selected=name===state.route,m=Number(terminal?.mobs_per_hour||0),isTerminalBest=terminalBest>0&&Math.abs(m-terminalBest)<1e-9,status=cr.status||route.status||'unavailable',reason=cr.reason||route.reason||'';return `<div class="spec-row ${selected?'sel':''}" data-route="${esc(name)}"><div><b>${esc(routeLabel(state.cls,name))}</b> ${name==='unconstrained'?badge('CUMULATIVE OPTIMUM','opt'):''}${isTerminalBest?badge(`L${target} FASTEST`,''):''}${status!=='available'?badge('UNAVAILABLE','warn'):''}</div><div>${rr.regret_percent==null?'regret —':`regret <b>${Number(rr.regret_percent).toFixed(2)}%</b><div class="small muted">${esc(rr.constraint_label||routeLabel(state.cls,name))} · ${esc(rr.constraint_source||'route_registry')} · ${esc(rr.regret_authority||rr.authority||'canonical')}</div>`}</div><div><b>${m>0?mph(m):'—'}</b><div class="small muted">${status==='available'?`route-specific scorer at L${target}`:esc(reason||status)}</div></div><div class="small muted">${esc(terminal?.combat_profile||terminal?.talent_family||terminal?.allocation||status)}</div></div>`}).join('')+`<div class="small muted" style="margin-top:7px">Regret = constrained cumulative objective − unrestricted cumulative objective from the same canonical LevelFrontier + DP authority. Constraint label/source is shown per route. Terminal throughput/profile uses the route-specific fixed-route scorer when available.</div>`:'<div class="muted">No route comparison for this target.</div>';document.querySelectorAll('.spec-row[data-route]').forEach(el=>el.onclick=()=>{state.route=el.dataset.route;syncState();renderAll();scrollToLevel()})}
function routeRows(){if(state.route==='per_level_best'){return (data?.per_level_rows?.[state.cls]||[]).filter(r=>Number(r.level)<=Number(state.target)).map(r=>({...r,level:Number(r.level),_transition:null}));}const route=targetMeta(state.cls,state.target)?.routes?.[state.route]||{},trans=new Map((route.transitions||[]).map(x=>[Number(x.level),x]));return routeRowsFor(state.cls,state.target,state.route).map(row=>({...row,level:Number(row.level),_transition:trans.get(Number(row.level))}))}
function routeUnavailableReason(){const cr=data?.route_rows?.[state.cls]?.[String(state.target)]?.routes?.[state.route]||{},er=targetMeta(state.cls,state.target)?.routes?.[state.route]||{};return cr.reason||er.reason||((cr.status&&cr.status!=='available')?cr.status:'')}
function changeText(row){const c=row?._transition?.changes||{},parts=[];for(const [k,v] of Object.entries(c)){if(k==='talent_added')continue;parts.push(`${k} → ${v}`)}return parts.join(' · ')||'talent allocation update'}
function gearSummary(row){const g=row?.gear_stats;if(!g)return 'gear unavailable';const cov=gearCoverage(g);return `${cov.used.length} named item${cov.used.length===1?'':'s'}${cov.catalogueOnly.length?` · ${cov.catalogueOnly.length} more slots covered by catalogue`:''}${cov.missing.length?` · ${cov.missing.length} missing catalogue slot${cov.missing.length===1?'':'s'}`:''}`}
function talentTrees(row){const canonical=row?.talent_trees||{};if(Object.keys(canonical).length)return canonical;const points=row?.tree_points||{},ranks=row?.talent_ranks||{},out={},txt=String(row?.allocation||'');for(const m of txt.matchAll(/([a-zA-Z][a-zA-Z0-9_]*)\((\d+)\)(?:\[([^\]]*)\])?/g)){const tree=String(m[1]).toLowerCase(),talents=[],body=m[3]||'';for(const part of body.split(',')){const mm=part.trim().match(/^([a-zA-Z0-9_]+):(\d+)$/);if(mm){const name=mm[1],parsed=Number(mm[2]);talents.push({name,rank:Number(ranks[name]??parsed)})}}out[tree]={points:Number(points[tree]??m[2]??talents.reduce((a,x)=>a+x.rank,0)),talents}}return out}
function talentMeta(row,name){const key=String(name||'');for(const tree of Object.values(talentTrees(row)||{})){for(const t of (tree?.talents||[])){if(String(t?.name||'')===key)return t?.icon||null}}return null}
function prettyTalent(x){return String(x||'').split('_').map(w=>w? w[0].toUpperCase()+w.slice(1):w).join(' ')}
function routeLabel(cls,route){return classMeta(cls).route_labels?.[route]||prettyTalent(route)}
function wowheadEntityReady(meta){return !!(meta?.entity_verified&&meta?.entity_id&&meta?.provenance_url)}
function wowheadLink(label,meta,extra='',innerHtml=null){if(!wowheadEntityReady(meta))return innerHtml??`<span>${esc(label)}</span>`;const title=`${label} · ${meta.provenance_source||'exact entity provenance'}`;return `<a class="wowhead-entity ${esc(extra)}" href="${esc(meta.provenance_url)}" target="_blank" rel="noreferrer" title="${esc(title)}" data-wh-icon-size="small" data-wh-rename-link="false" data-entity-kind="${esc(meta.entity_kind||'')}" data-entity-id="${esc(meta.entity_id)}">${innerHtml??esc(label)}</a>`}
function entityLabel(label,meta,extra=''){const icon=meta?.icon_verified&&meta?.icon_url?`<img class="entity-icon" src="${esc(meta.icon_url)}" loading="lazy" alt="" onerror="this.style.display='none'">`:'';const text=`<span>${esc(label)}</span>`;const content=`${icon}${text}`;const title=`${label} · ${meta?.icon_provenance_source||meta?.provenance_source||'verified entity provenance'}`;const attrs=meta?.icon_verified?` data-icon-provider="${esc(meta.icon_provider||'')}" data-icon-key="${esc(meta.icon_key||'')}"`:'';if(wowheadEntityReady(meta)){return `<span class="entity-label ${esc(extra)}"${attrs}>${wowheadLink(label,meta,extra,content)}</span>`}return `<span class="entity-label ${esc(extra)}"${attrs} title="${esc(title)}">${content}</span>`}
let wowheadRefreshTimer=null;
function refreshWowheadLinks(retries=6){clearTimeout(wowheadRefreshTimer);try{if(window.$WowheadPower?.refreshLinks){window.$WowheadPower.refreshLinks();return}}catch(_e){}if(retries>0)wowheadRefreshTimer=setTimeout(()=>refreshWowheadLinks(retries-1),120)}
function rotationSteps(row){if(Array.isArray(row?.rotation_steps)&&row.rotation_steps.length)return row.rotation_steps.map(x=>typeof x==='string'?{label:x}:{...x,label:String(x?.label||'')}).filter(x=>x.label);return String(row?.rotation||row?.policy||'—').split(/;| → |\\s+then\\s+/i).map(x=>({label:x.trim()})).filter(x=>x.label)}
function statWeightModel(row){
  const sw=row?.stat_weights||row?.details?.stat_weights||{},st=sw.stats||{},eps=1e-12;
  if(Object.keys(st).length){
    const native=k=>st?.[k]?.status&&st[k].status!=='measured'?NaN:(st?.[k]?.seconds_saved_per_100_per_point==null?NaN:Number(st[k].seconds_saved_per_100_per_point));
    let ref=sw.reference_stat;
    if(!ref||!Number.isFinite(native(ref))||native(ref)<=eps){
      ref=['spell_power','spell_damage','attack_power','strength','agility','weapon_dps','intellect',...Object.keys(st)].find(k=>Number.isFinite(native(k))&&native(k)>eps);
    }
    const refValue=ref?native(ref):NaN;
    // Always use native values: null is missing, never a numeric zero, and a
    // fallback reference must also rebase every weight to that same reference.
    const rows=Object.keys(st).map(k=>[k,Number.isFinite(refValue)?native(k)/refValue:native(k)]).filter(([,v])=>Number.isFinite(v)).sort((a,b)=>b[1]-a[1]);
    if(rows.length)return {rows,reference:ref||null,kind:ref?'equivalent':'raw'};
  }
  const raw=sw.weights||sw.curve_sensitivity||{};
  const rows=Object.entries(raw).map(([k,v])=>[k,Number(typeof v==='object'?(v.relative_percent_per_unit??v.relative_percent):v)]).filter(([,v])=>Number.isFinite(v)&&v>=0).sort((a,b)=>b[1]-a[1]);
  return {rows,reference:null,kind:'raw'};
}
function weightRows(row){return statWeightModel(row).rows.slice(0,8)}
function statRefLabel(stat){const labels={spell_power:'SP',spell_damage:'SP',attack_power:'AP',healing:'Healing',strength:'Str',agility:'Agi',intellect:'Int'};return labels[stat]||prettyTalent(stat||'weight')}
function itemStatAmount(item,stat){const aliases={spell_damage:'spell_power',attack_power:'attack_power'};const key=aliases[stat]||stat;const value=key==='spell_power'?Math.max(Number(item?.spell_power||0),Number(item?.spell_damage||0)):item?.[key];const v=Number(value);return Number.isFinite(v)?v:0}
function itemEquivalentScore(item,row){const model=statWeightModel(row);if(model.kind!=='equivalent'||!model.rows.length)return null;let total=0,used=0;for(const [stat,w] of model.rows){const amount=itemStatAmount(item,stat);if(Math.abs(amount)>1e-12){total+=amount*w;used++}}return used?{value:total,reference:model.reference,label:statRefLabel(model.reference)}:null}
function itemToolWeights(row){return Object.fromEntries(statWeightModel(row).rows.filter(([,v])=>Number.isFinite(Number(v))).map(([k,v])=>[k,Number(v)]))}
function currentFocusRow(){const rows=routeRows();return rows.find(r=>Number(r.level)===Number(state.level))||rows.at(-1)||null}
function gearToolHtml(row,gear){const options=gear.used.map(x=>`<option value="${esc(x.slot)}">${esc(prettyTalent(x.slot))} · ${esc(x.name||x.item||'—')}</option>`).join('');return `<div class="coverage-box small" style="margin-top:10px"><b>My gear / item compare</b><div class="small muted" style="margin:4px 0 7px">Lock an exact item into one slot for a canonical recompute; unpinned slots still optimize. Item A/B preview uses this level's published stat weights.</div><div class="toolbar"><select id="gearToolSlot">${options}</select><input id="gearToolCandidate" type="text" placeholder="item ID or Wowhead Forever URL" style="width:270px"><button type="button" onclick="runItemCompare()">Compare</button><button type="button" onclick="queueGearOverride()">Lock & recompute</button><button type="button" onclick="openUpgradeSearch()">Find upgrades</button></div><div id="gearToolResult" class="small muted" style="margin-top:7px">${options?'Choose a slot and paste an item.':'No named equipped slot to compare.'}</div></div>`}
async function runItemCompare(){const row=currentFocusRow(),slot=$('gearToolSlot')?.value,cand=String($('gearToolCandidate')?.value||'').trim(),box=$('gearToolResult');if(!row||!slot||!cand){if(box)box.textContent='Choose an equipped slot and paste an item ID/URL.';return}const cur=row?.gear_stats?.slots?.[slot]||{},id=cur.item_id;if(!id){box.textContent='Selected equipped item has no exact item ID; comparison fails closed.';return}box.textContent='Comparing with published stat weights…';try{const r=await fetch('/api/decisions/item-compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class:state.cls,level:Number(state.level),item_a:id,item_b:cand,weights:itemToolWeights(row)})}),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);const a=j.item_a||{},b=j.item_b||{},d=Number(j.score_delta_b_minus_a||0),delta=Object.entries(j.stat_delta_b_minus_a||{}).map(([k,v])=>`${prettyTalent(k)} ${Number(v)>=0?'+':''}${fmtNum(v,2)}`).join(' · ');box.innerHTML=`<b>${esc(a.name||'#'+id)} → ${esc(b.name||cand)}</b> · ${d>=0?'+':''}${fmtNum(d,2)} weighted units · ${badge(j.winner==='b'?'candidate wins':(j.winner==='a'?'equipped wins':'tie'),j.winner==='b'?'good':(j.winner==='a'?'warn':''))}<div class="small">${esc(delta||'no modeled stat delta')}</div><div class="small muted">${esc(j.note||'')}</div>`}catch(e){box.textContent='Comparison failed: '+e}}
async function queueGearOverride(){const row=currentFocusRow(),slot=$('gearToolSlot')?.value,cand=String($('gearToolCandidate')?.value||'').trim(),box=$('gearToolResult');if(!row||!slot||!cand){if(box)box.textContent='Choose a slot and paste an exact item ID/URL.';return}const m=cand.match(/(?:item=|^#?)(\d+)/);if(!m){box.textContent='Lock requires an exact numeric item ID or Wowhead item URL.';return}const itemId=Number(m[1]);box.textContent='Queueing canonical recompute with this locked slot…';try{const payload={ruleset:'forever',class_name:state.cls,start_level:Number(state.level),end_level:Number(state.level),objective:'endpoint',endpoint_mode:'smooth',config:{workers:1,gear_overrides:{[slot]:itemId}}};const r=await fetch('/api/service/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);box.innerHTML=`${badge('queued','good')} locked ${esc(prettyTalent(slot))}=#${itemId} · other slots remain optimizer-owned · job ${esc(j.job?.job_id||j.job?.id||'created')}`;setTimeout(refreshService,250)}catch(e){box.textContent='Queue failed: '+e}}
async function openUpgradeSearch(){const row=currentFocusRow(),slot=$('gearToolSlot')?.value,box=$('gearToolResult');if(!row||!slot)return;try{const r=await fetch('/api/decisions/upgrade-search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class:state.cls,level:Number(state.level),slot,weights:itemToolWeights(row)})}),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);window.open(j.url,'_blank','noopener,noreferrer');const omitted=(j.omitted_weight_filters||[]).map(prettyTalent).join(', ');box.innerHTML=`Opened source-backed Wowhead class/level search for ${esc(prettyTalent(slot))}.<div class="small muted">Stat filters intentionally omitted until their Wowhead numeric filter mapping is verified${omitted?`: ${esc(omitted)}`:''}.</div>`}catch(e){box.textContent='Upgrade search failed: '+e}}
function focusGearRows(row){const g=row?.gear_stats;if(!g)return {used:[],missing:[],blocked:[]};const cov=gearCoverage(g),slots=g.slots||{};return {used:cov.used.map(slot=>({slot,...(slots[slot]||{})})),missing:cov.missing,blocked:cov.blocked}}
function referenceSnapshot(){return data?.reference_builds?.[state.cls]||null}
function referenceRows(){const snap=referenceSnapshot();return snap?.builds||[]}
function referenceBuildTypeForSelection(){if(state.route==='feral_cat'||state.route==='feral_bear')return 'feral';if(['balance','restoration'].includes(state.route))return state.route;const rows=routeRows(),row=rows.find(r=>Number(r.level)===Number(state.level))||rows.at(-1)||{};return String(row.talent_family||'').toLowerCase()}
function referenceTreePoints(row){const trees=talentTrees(row),names=classMeta(state.cls).tree_names||Object.keys(trees);const out={};for(const name of names)out[String(name).toLowerCase()]=Number(trees?.[name]?.points??trees?.[String(name).toLowerCase()]?.points??0);return out}
function referenceRankDiff(row,ref){const actual=row?.talent_ranks||{},wanted=ref?.talent_ranks||{};if(!Object.keys(wanted).length)return [];const keys=[...new Set([...Object.keys(actual),...Object.keys(wanted)])].sort();return keys.map(k=>({name:k,optimizer:Number(actual[k]||0),reference:Number(wanted[k]||0)})).filter(x=>x.optimizer!==x.reference)}
function referencePrefixAtLevel(ref,level){const exact=ref?.prefixes_by_level?.[String(Number(level))]||null;if(exact)return {...exact,status:'exact_source_leveling_order'};const refLevel=Number(ref?.level||60);if(Number(level)===refLevel&&ref?.allocation_detail_status==='exact')return {level:refLevel,tree_points:ref.tree_points||{},talent_ranks:ref.talent_ranks||{},allocation:ref.allocation||'',status:'exact_final_allocation'};return null}
function renderBuildComparison(){
  const box=$('compareBuildResult');if(!box)return;
  const c=lastBuildComparison;
  if(!c){box.innerHTML='<div class="small muted">No pasted build comparison yet.</div>';return}
  if(c.status!=='available'){
    box.innerHTML=`<div class="continuation-result warn"><b>Comparison unavailable</b><div class="small">${esc(c.error||c.note||'Unknown comparison error.')}</div>${c.source_url?`<div class="small"><a href="${esc(c.source_url)}" target="_blank" rel="noreferrer">Open source build ↗</a></div>`:''}</div>`;return;
  }
  if(String(c.class)!==String(state.cls)||Number(c.target_level)!==Number(state.target)||String(c.route)!==String(state.route)||Number(c.level)!==Number(state.level)){
    box.innerHTML='<div class="continuation-result warn"><b>Selection changed</b><div class="small">Run Compare to build again for the currently selected route/level.</div></div>';return;
  }
  const o=c.optimizer||{},r=c.challenger||{},d=c.delta||{},pct=d.challenger_minus_optimizer_percent,delta=d.challenger_minus_optimizer_mobs_per_hour,td=c.talent_divergence||[];
  const faster=c.challenger_faster;
  const verdict=pct==null?'delta —':`${Number(delta)>=0?'+':''}${Number(delta).toFixed(1)} mobs/h · ${Number(pct)>=0?'+':''}${Number(pct).toFixed(2)}%`;
  const source=c.source||{},h=c.comparison_horizon||{},horizon=(h.through_level!=null?`Compared through L${Number(h.through_level)} · ${Number(h.reference_points_used||0)}/${Number(h.reference_endpoint_points||0)} reference points`:'');
  box.innerHTML=`<div class="small" style="margin-bottom:7px">${badge(c.mode==='same_gear'?'SAME GEAR':'OWN OPTIMIZED GEAR','opt')} ${badge('profile '+(c.profile||'—'))} ${source.progression_status?badge(source.progression_status):''} · <a href="${esc(source.url||'#')}" target="_blank" rel="noreferrer">TalentsForever source ↗</a>${horizon?` · <span class="good">${esc(horizon)}</span>`:''}</div>
  <div class="grid2"><div class="cmp-card"><b>Optimizer · L${esc(c.level)}</b><div class="kpi">${mph(o.mobs_per_hour)}</div><div class="small muted">${esc(timingSummary(o))}</div><div class="allocation"><code>${esc(o.allocation||'—')}</code></div><div class="small"><b>rotation</b> · <code>${esc(o.rotation||o.policy||'—')}</code></div><div class="small weights" style="margin-top:6px"><b>stat weights</b> · ${esc(statWeightSummary(o))}</div><div class="small muted" style="margin-top:5px">${esc(gearSummary(o))}</div></div>
  <div class="cmp-card"><b>Challenger · TalentsForever</b><div class="kpi">${mph(r.mobs_per_hour)}</div><div class="small muted">${esc(timingSummary(r))}</div><div class="allocation"><code>${esc(r.allocation||'—')}</code></div><div class="small"><b>rotation</b> · <code>${esc(r.rotation||r.policy||'—')}</code></div><div class="small weights" style="margin-top:6px"><b>stat weights</b> · ${esc(statWeightSummary(r))}</div><div class="small muted" style="margin-top:5px">${esc(gearSummary(r))}</div></div></div>
  <div class="continuation-result ${faster?'warn':'good'}" style="margin-top:8px"><b>Challenger − optimizer: ${esc(verdict)}</b><div class="small">${esc(c.mode_label||'')}</div>${c.search_gap_note?`<div class="small warn">${esc(c.search_gap_note)}</div>`:''}</div>
  <div class="small" style="margin-top:8px"><b>Timing delta · challenger − optimizer:</b> mob ${sec(d.timing?.seconds_per_mob)} · kill ${sec(d.timing?.kill_seconds_per_mob)} · recovery ${sec(d.timing?.recovery_seconds_per_mob)} · travel ${sec(d.timing?.travel_seconds_per_mob)}</div>
  <div class="small" style="margin-top:7px"><b>Talent divergence (${td.length}):</b> ${td.length?td.slice(0,28).map(x=>`${prettyTalent(x.talent)} ${x.optimizer}→${x.challenger}`).join(' · '):'<span class="good">same exact ranks</span>'}${td.length>28?' · …':''}</div>
  <div class="small muted" style="margin-top:7px">External challenger · comparison only · search authority false · route authority false.</div>`;
}
async function runBuildComparison(){
  const input=$('compareBuildUrl'),button=$('compareBuildRun'),box=$('compareBuildResult'),url=String(input?.value||'').trim(),mode=$('compareBuildMode')?.value||'same_gear';
  if(!url){box.innerHTML='<div class="continuation-result warn">Paste a TalentsForever build URL first.</div>';return}
  localStorage.setItem('foreverCompareBuildUrl',url);localStorage.setItem('foreverCompareBuildMode',mode);
  button.disabled=true;box.innerHTML='<div class="small muted">Scoring challenger through the canonical class model…</div>';
  try{
    const resp=await fetch('/api/decisions/compare-build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class:state.cls,target_level:Number(state.target),route:state.route,level:Number(state.level),source_url:url,mode})});
    let j={};try{j=await resp.json()}catch(_e){j={status:'error',error:`comparison HTTP ${resp.status}`}}
    if(!resp.ok&&j.status!=='unavailable')j={...j,status:j.status||'error',error:j.error||`comparison HTTP ${resp.status}`};
    lastBuildComparison=j;renderBuildComparison();
  }catch(e){lastBuildComparison={status:'error',error:String(e),source_url:url};renderBuildComparison()}
  finally{button.disabled=false;renderFocus()}
}
function renderReferenceCompare(){
  const panel=$('referencePanel'),pick=$('referencePick'),storedLabel=$('storedReferenceLabel'),coverage=$('referenceCoverage'),box=$('referenceCompare'),snap=referenceSnapshot(),refs=referenceRows();
  if(!panel||!pick||!coverage||!box)return;panel.style.display='block';renderBuildComparison();
  if(!snap||!refs.length){storedLabel.style.display='none';coverage.textContent='No stored reference snapshot for this class. You can still paste a supported TalentsForever URL above.';box.innerHTML='';return}
  storedLabel.style.display='';
  const previous=pick.value,groups=snap.groups||{},wantedType=referenceBuildTypeForSelection();
  pick.innerHTML=Object.entries(groups).map(([key,g])=>{const rows=g.builds||[];return rows.length?`<optgroup label="${esc(g.label||prettyTalent(key))} · ${rows.length}/${Number(g.requested||3)} source-visible">${rows.map(r=>`<option value="${esc(r.id)}">${esc(r.label||r.id)}</option>`).join('')}</optgroup>`:''}).join('');
  const previousRef=refs.find(r=>r.id===previous),selected=(previousRef&&String(previousRef.build_type||'').toLowerCase()===wantedType?previousRef:null)||refs.find(r=>String(r.build_type||'').toLowerCase()===wantedType)||previousRef||refs[0];if(selected)pick.value=selected.id;
  const gaps=Object.entries(groups).filter(([,g])=>!g.coverage_complete).map(([k,g])=>`${g.label||prettyTalent(k)} ${g.available||0}/${g.requested||3}`);
  coverage.innerHTML=`Stored source: <a href="${esc(snap.source?.provider_url||'#')}" target="_blank" rel="noreferrer">${esc(snap.source?.provider||'reference source')}</a> · requested top ${Number(snap.requested_per_build_type||3)}/type${gaps.length?` · <span class="warn">source surface incomplete: ${esc(gaps.join(' · '))}</span>`:' · complete'}`;
  if(!selected){box.innerHTML='';return}
  const rows=routeRows(),row=rows.find(r=>Number(r.level)===Number(state.level))||rows.at(-1)||{},optPoints=referenceTreePoints(row),treeNames=['balance','feral','restoration'];
  const prefix=referencePrefixAtLevel(selected,Number(row.level??state.level)),refPoints=prefix?.tree_points||selected.tree_points||{};
  const finalSplit=treeNames.map(k=>Number(selected.tree_points?.[k]||0)).join('/'),split=prefix?treeNames.map(k=>Number(refPoints[k]||0)).join('/'):finalSplit,optSplit=treeNames.map(k=>Number(optPoints[k]||0)).join('/');
  const deltas=prefix?treeNames.map(k=>`${prettyTalent(k)} ${Number(optPoints[k]||0)-Number(refPoints[k]||0)>=0?'+':''}${Number(optPoints[k]||0)-Number(refPoints[k]||0)}`).join(' · '):null,diff=prefix?referenceRankDiff(row,prefix):[];
  const pop=selected.popularity||{},exact=selected.allocation_detail_status==='exact',src=selected.source_url||snap.source?.provider_url||'#',selectedType=String(selected.build_type||'').toLowerCase(),crossType=!!wantedType&&selectedType!==wantedType;
  const compareLevel=Number(row.level??state.level),prefixLabel=prefix?`Compared through L${compareLevel} · ${Number(prefix.points??Object.values(prefix.talent_ranks||{}).reduce((a,b)=>a+Number(b||0),0))}/${Object.values(selected.tree_points||{}).reduce((a,b)=>a+Number(b||0),0)} reference points · ${prefix.status==='exact_source_leveling_order'?'TalentsForever leveling order':'exact final allocation'}`:`Final L${Number(selected.level||60)} split shown only · no source-backed L${compareLevel} prefix`;
  box.innerHTML=`${crossType?`<div class="small warn" style="margin-bottom:7px"><b>Cross-family reference:</b> selected ${esc(prettyTalent(selectedType))}, current optimizer family ${esc(prettyTalent(wantedType))}.</div>`:''}<div class="grid2"><div class="cmp-card"><b>Optimizer · L${esc(row.level??state.level)}</b><div class="kpi">${esc(optSplit)}</div><div class="small muted">${esc(row.allocation||'machine-readable allocation unavailable')}</div>${row.mobs_per_hour!=null?`<div>${mph(row.mobs_per_hour)}</div>`:''}</div><div class="cmp-card"><b>${esc(prettyTalent(selected.build_type))} stored reference</b><div class="kpi">${esc(split)}</div><div class="small">${badge('#'+selected.overall_rank+' overall')} ${exact?badge('exact ranks','good'):badge('family split only','warn')}</div><div class="small ${prefix?'good':'warn'}">${esc(prefixLabel)}</div><div class="small muted">shared ${Number(pop.shared||0)} · saved ${Number(pop.saved||0)} · opened ${Number(pop.opened||0)} · ${Number(pop.close_builds||0)} close builds</div><div class="small"><a href="${esc(src)}" target="_blank" rel="noreferrer">Open source build ↗</a>${exact?` · <button type="button" data-ref-compare-url="${esc(src)}">Compare this build</button>`:''}</div></div></div>${prefix?`<div class="small" style="margin-top:8px"><b>Tree-point delta · optimizer − L${compareLevel} reference prefix:</b> ${esc(deltas)}</div><div class="small" style="margin-top:7px"><b>Exact talent delta (${diff.length}):</b> ${diff.length?diff.slice(0,20).map(x=>`${prettyTalent(x.name)} ${x.optimizer}→${x.reference}`).join(' · '):'<span class="good">same exact ranks</span>'}${diff.length>20?' · …':''}</div>`:`<div class="small warn" style="margin-top:8px"><b>Lower-level delta unavailable:</b> this stored reference has no source-backed leveling order for L${compareLevel}; final L${Number(selected.level||60)} points are not compared against the optimizer.</div>`}<div class="small muted" style="margin-top:7px">Use Compare this build to score exact references through the same level-aware comparator as pasted URLs.</div>`;
}
function genericDecisionModelHtml(row){
  const c=row?.decision_content||{},actors=Array.isArray(c.actors)?c.actors:[],resources=Array.isArray(c.resources)?c.resources:[],actions=Array.isArray(c.actions)?c.actions:[],modes=Array.isArray(c.modes)?c.modes:[],policy=c.policy||{};
  if(!actors.length&&!resources.length&&!actions.length&&!modes.length)return '<div class="small muted">Generic gameplay projection not available for this legacy row yet.</div>';
  const actor=actors[0]||{},activeMode=modes.find(x=>x?.active)||modes[0],activeResources=resources.filter(x=>x?.active!==false),actionLabels=actions.map(x=>x?.label||x?.id).filter(Boolean);
  return `<div class="small"><b>${esc(actor.kind||'actor')}</b> · ${esc(actor.id||'player')}${activeMode?` · mode <b>${esc(prettyTalent(activeMode.id||'—'))}</b>`:''}</div>
    <div class="small muted">resources · ${activeResources.length?activeResources.map(x=>esc(prettyTalent(x.id||'—'))).join(' · '):'—'}</div>
    <div class="small muted">actions · ${actionLabels.length?actionLabels.map(esc).join(' → '):'—'}</div>
    <div class="small muted">policy · ${esc(policy.kind||'—')} · ${esc(policy.structure_status||'—')}</div>`;
}
function focusDecisionContextHtml(row,rr){
  const lvl=Number(row?.level),ep=data?.endpoint_paths?.[state.cls]||{},fid=ep.model_fidelity||{};
  const regret=state.route==='unconstrained'?0:Number(rr?.regret_percent);
  const regretText=Number.isFinite(regret)?`${regret.toFixed(2)}%`:'—';
  const dual=data?.dual_spec?.[state.cls]||{},switches=dual.switch_points||[];
  const nextSwitch=switches.find(x=>Number(x.level)>lvl)||null;
  const cont=lastContinuation;
  const contMatches=cont&&String(cont.class)===String(state.cls)&&Number(cont.target_level)===Number(state.target);
  let contHtml='<div class="small muted">Custom current talents not evaluated yet.</div>';
  if(contMatches){
    if(cont.status==='available'){
      const c=cont.continuation||{},nt=c.next_talent_pick||{},nm=c.next_meaningful_decision||{};
      contHtml=`<div>${badge('available','good')} ${badge('regret '+Number(cont.regret_percent||0).toFixed(2)+'%',Number(cont.regret_percent||0)>5?'warn':'')}</div>${nt.level?`<div class="small"><b>next talent</b> · L${nt.level} · ${esc(nt.talent_added||'—')}</div>`:''}${nm.level?`<div class="small"><b>next decision</b> · L${nm.level}</div>`:''}`;
    }else contHtml=`<div>${badge(cont.status||'unavailable','warn')}</div><div class="small muted">${esc(cont.note||'No preserved corridor matches the exact current allocation.')}</div>`;
  }
  const cmp=lastBuildComparison,cmpMatches=cmp&&cmp.status==='available'&&String(cmp.class)===String(state.cls)&&Number(cmp.target_level)===Number(state.target)&&String(cmp.route)===String(state.route)&&Number(cmp.level)===lvl;
  const cmpHtml=cmpMatches?`<div>${badge(cmp.mode==='same_gear'?'same gear':'own optimized gear','opt')}</div><div class="small"><b>challenger Δ</b> ${Number(cmp.delta?.challenger_minus_optimizer_mobs_per_hour||0)>=0?'+':''}${fmtNum(cmp.delta?.challenger_minus_optimizer_mobs_per_hour,1)} mobs/h · ${fmtNum(cmp.delta?.challenger_minus_optimizer_percent,2)}%</div>`:'<div class="small muted">No active exact challenger comparison for this level.</div>';
  const cap=`verified ≤L${esc(ep.verified_level_cap??fid.verified_level_cap??'—')} · planning ≤L${esc(ep.planning_level_cap??fid.planning_level_cap??'—')} · ${esc(fid.rating||'unknown')}`;
  const src=esc((row?.data_sources||[]).join(' + ')||row?.source||'unknown');
  const backend=row?.decision_contract?.backend||{},backendLabel=backend.id?`${backend.id}${backend.version?'@'+backend.version:''}`:'legacy';
  return `<div class="focus-panel"><div class="focus-title">Decision context</div>
    <div class="decision-context-grid">
      <div class="subpanel"><div class="subpanel-title">Regret</div><div><b>${esc(regretText)}</b> ${state.route==='unconstrained'?'<span class="small muted">unrestricted baseline</span>':`<span class="small muted">${esc(rr?.constraint_label||routeLabel(state.cls,state.route))}</span>`}</div></div>
      <div class="subpanel"><div class="subpanel-title">Continuation</div>${contHtml}<button type="button" data-focus-action="continuation" style="margin-top:6px">Use my current talents</button></div>
      <div class="subpanel"><div class="subpanel-title">Dual spec</div>${dual.status==='available'?`<div class="small"><b>${esc(dual.pair?.A?.route||'A')}</b> + <b>${esc(dual.pair?.B?.route||'B')}</b></div><div class="small muted">${nextSwitch?`next switch L${esc(nextSwitch.level)} → ${esc(nextSwitch.to_route||nextSwitch.to_slot||'secondary')} · level boundary`:'no later switch in this window'}</div>`:`<div class="small muted">${esc(dual.reason||dual.status||'not available')}</div>`}</div>
      <div class="subpanel"><div class="subpanel-title">Fidelity / provenance</div><div class="small">${cap}</div><div class="small muted">backend ${esc(backendLabel)} · ${src} · row ${esc(row?.decision_row_id||'—')}</div></div>
      <div class="subpanel"><div class="subpanel-title">Generic gameplay model</div>${genericDecisionModelHtml(row)}</div>
      <div class="subpanel decision-compare"><div class="subpanel-title">Compare to build</div><div class="controls"><input id="focusCompareBuildUrl" type="text" placeholder="TalentsForever URL" value="${esc(localStorage.getItem('foreverCompareBuildUrl')||'')}" style="min-width:240px;flex:1"><button type="button" data-focus-action="compare">Compare</button></div>${cmpHtml}</div>
    </div></div>`;
}
function renderFocus(){
  const rows=routeRows(),row=rows.find(r=>Number(r.level)===Number(state.level))||rows.at(-1);
  if(!row){
    $('focusTitle').textContent='Selected level';
    $('focusSubtitle').textContent='No row available';
    $('focusBadges').innerHTML='';
    $('focusBoard').innerHTML='<div class="focus-empty">No selected-level data.</div>';
    return;
  }
  const nativeContext=genericNativeRouteContext(row);
  const lvl=Number(row.level),trees=talentTrees(row),weightModel=statWeightModel(row),weights=weightModel.rows.slice(0,8),maxw=Math.max(0,...weights.map(x=>x[1])),gear=focusGearRows(row),rr=data?.spec_regret?.[state.cls]?.targets?.[String(state.target)]?.routes?.[state.route]||{},missing=row.missing||{};
  const treeNames=classMeta(state.cls).tree_names||Object.keys(trees);
  const treePoints=treeNames.map(tree=>Number(trees?.[tree]?.points??(trees?.[tree]?.talents||[]).reduce((a,x)=>a+Number(x.rank||0),0)));
  const totalPoints=treePoints.reduce((a,x)=>a+x,0);
  const activeTree=treeNames[treePoints.indexOf(Math.max(...treePoints,0))]||row.talent_family||state.route;
  const gearLabel=prettyTalent(String(row.gear||'—').replace(/_normal$/,'').replace(/^1h$/,'1H').replace(/^2h$/,'2H'));
  const profileLabel=prettyTalent(row.combat_profile||row.talent_family||'—');

  $('focusTitle').textContent=`Level ${lvl} — ${routeLabel(state.cls,state.route)}`;
  $('focusSubtitle').textContent=`${prettyTalent(state.cls)} · target L${state.target} · ${state.route==='unconstrained'?'cumulative optimum route':(state.route==='per_level_best'?'fastest searched build at each level · ~1s respec':routeLabel(state.cls,state.route))}${nativeContext.proxy?' · proxy weapon/base stats; no named gear':''}`;
  $('focusBadges').innerHTML=`${badge(mph(row.mobs_per_hour),'opt')}${state.route==='unconstrained'?badge('cumulative optimum','opt'):(state.route==='per_level_best'?badge('per-level fastest','opt'):badge('regret '+(rr.regret_percent==null?'—':Number(rr.regret_percent).toFixed(2)+'%'),Number(rr.regret_percent||0)>5?'warn':''))}${nativeContext.proxy?badge('proxy scenario · not cross-class comparable','warn'):''}`;

  const treeHtml=treeNames.map((tree,i)=>{
    const t=trees?.[tree]||{},talents=t?.talents||[],points=treePoints[i]||0;
    return `<div class="talent-tree ${points>0?'active-tree':''}"><h4>${esc(prettyTalent(tree))} (${points})</h4>${talents.length?talents.map(x=>{const label=prettyTalent(x.name);return `<div class="talent-node active">${entityLabel(label,x.icon,'talent-icon')}<span class="talent-rank">${Number(x.rank||0)}</span></div>`}).join(''):'<div class="small muted">No points</div>'}</div>`
  }).join('');
  const talentSummary=treeNames.flatMap(tree=>(trees?.[tree]?.talents||[]).filter(x=>Number(x.rank||0)>0).map(x=>({tree,name:x.name,rank:Number(x.rank||0)})));
  const talentTable=talentSummary.length?`<table class="talent-summary"><thead><tr><th>Talent</th><th>Tree</th><th>Points</th></tr></thead><tbody>${talentSummary.map(x=>`<tr><td>${entityLabel(prettyTalent(x.name),x.icon,'talent-icon')}</td><td class="muted">${esc(prettyTalent(x.tree))}</td><td>${x.rank}</td></tr>`).join('')}</tbody></table>`:'';

  const rot=rotationSteps(row);
  const rowIndex=rows.findIndex(x=>Number(x.level)===lvl),prevRow=rowIndex>0?rows[rowIndex-1]:null,prevSlots=prevRow?.gear_stats?.slots||{},scoreUnit=weightModel.kind==='equivalent'?`${statRefLabel(weightModel.reference)}-eq`:null;
  const gearHtml=gear.used.length?`<table class="focus-gear"><thead><tr><th>Slot</th><th>Item</th><th>Stats</th><th>${esc(scoreUnit||'Value')}</th></tr></thead><tbody>${gear.used.map(x=>{const name=x.name||x.item||'—',score=itemEquivalentScore(x,row),prev=prevSlots?.[x.slot],prevScore=prev?itemEquivalentScore(prev,row):null,changed=prev&&String(prev.name||prev.item||'')!==String(name),delta=score&&prevScore?score.value-prevScore.value:null,deltaText=changed&&Number.isFinite(delta)?`${delta>=0?'+':''}${fmtNum(delta,1)} vs L${Number(prevRow.level)}`:'';return `<tr><td>${esc(prettyTalent(x.slot||'—'))}</td><td class="item-name">${entityLabel(name,x.icon,'item-icon')}</td><td>${gearStatSummary(x)}</td><td>${score?`<b>${fmtNum(score.value,1)} ${esc(score.label)}-eq</b>${deltaText?`<div class="small ${delta>=0?'good':'warn'}">${esc(deltaText)}</div>`:''}`:'<span class="muted">—</span>'}</td></tr>`}).join('')}</tbody></table>`:`<div class="focus-empty">${esc(missing.gear||'No named items for this level.')}</div>`;

  const weightHtml=weights.length?weights.map(([k,v])=>{
    const width=maxw>0?(v<=0?0:Math.max(2,100*v/maxw)):0;
    return `<div class="weight-row"><span>${esc(prettyTalent(k))}</span><b>${fmtNum(v,2)}</b><div class="weight-track"><div class="weight-fill" style="width:${width.toFixed(1)}%"></div></div></div>`
  }).join(''):`<div class="small muted">${esc(missing.stat_weights||statWeightSummary(row))}</div>`;

  const total=Number(row.seconds_per_mob),timingParts=[
    ['Kill',Number(row.kill_seconds_per_mob),'kill'],
    ['Recovery',Number(row.recovery_seconds_per_mob),'recovery'],
    ['Travel',Number(row.travel_seconds_per_mob),'travel'],
  ].filter(([,v])=>Number.isFinite(v)&&v>=0);
  const timingHtml=timingParts.length?timingParts.map(([name,v,cls])=>{
    const pct=Number.isFinite(total)&&total>0?Math.max(0,Math.min(100,100*v/total)):0;
    return `<div class="timing-row"><span>${name}</span><b>${sec(v)}</b><div class="timing-track"><div class="timing-fill ${cls}" style="width:${pct.toFixed(1)}%"></div></div><span class="muted">${pct.toFixed(0)}%</span></div>`
  }).join(''):`<div class="small muted">${esc(missing.timing||'Detailed timing unavailable.')}</div>`;

  const config=[
    ['Gear',gearLabel],
    ['Profile',profileLabel],
    ['Pull size',row.pull_size==null?'—':String(row.pull_size)],
    ['Aura',prettyTalent(row.aura||'—')],
    ['Mana plan',prettyTalent(row.mana_plan||'—')],
    ['Policy',prettyTalent(row.policy||'—')],
  ];
  const configHtml=config.map(([k,v])=>`<div class="config-item"><b>${esc(k)}</b><span title="${esc(v)}">${esc(v)}</span></div>`).join('');
  const timingNote=missing.timing?`<div class="small warn" style="margin-top:7px">Timing · ${esc(missing.timing)}</div>`:'';
  const recoveryCycle=recoveryCycleSummary(row);
  const recoveryCycleHtml=recoveryCycle?`<div class="coverage-box small"><b>Recovery cycle</b><div class="muted" style="margin-top:3px">${esc(recoveryCycle)}</div></div>`:'';
  const talentNote=missing.talents?`<div class="small warn" style="margin-top:7px">${esc(missing.talents)}</div>`:'';
  const coverage=[gear.missing.length?`Missing catalogue: ${gear.missing.join(', ')}`:'',gear.blocked.length?`Blocked by setup: ${gear.blocked.join(', ')}`:''].filter(Boolean).join(' · ');

  $('focusBoard').innerHTML=`
    <div class="focus-col">
      <div class="focus-panel grow">
        <div class="focus-title">Level ${lvl} Talents</div>
        <div class="focus-subtitle">${totalPoints} points · ${esc(prettyTalent(activeTree))}</div>
        <div class="talent-tabs">${treeHtml}</div>
        ${talentTable}
        <details class="small muted" style="margin-top:9px"><summary>Allocation string</summary><code>${esc(row.allocation||'—')}</code></details>
        ${talentNote}
      </div>
    </div>
    <div class="focus-col">
      <div class="focus-panel">
        <div class="focus-title">Level ${lvl} Overview</div>
        <div class="focus-subtitle">${esc(profileLabel)} · ${esc(gearLabel)} · ${esc(prettyTalent(row.talent_family||activeTree))}</div>
        <div class="focus-kpis">
          <div class="focus-kpi"><b class="good">${mph(row.mobs_per_hour).replace(' mobs/h','')}</b><span class="unit">mobs/hour</span></div>
          <div class="focus-kpi"><b>${sec(row.seconds_per_mob)}</b><span class="unit">time per mob</span></div>
          <div class="focus-kpi"><b>${row.pull_size??'—'}</b><span class="unit">pull size</span></div>
          <div class="focus-kpi"><b>${sec(row.recovery_seconds_per_mob)}</b><span class="unit">recovery / mob</span></div>
        </div>
        ${timingNote}
        ${recoveryCycleHtml}
      </div>
      <div class="focus-panel">
        <div class="focus-title">Rotation &amp; Priority</div>
        <div class="rotation-list">${rot.map(x=>`<div class="rotation-step">${entityLabel(x.label,x.icon,'rotation-icon')}</div>`).join('')}</div>
        <div class="config-grid">
          <div class="subpanel"><div class="subpanel-title">Pull configuration</div><div class="config-list">${configHtml}</div></div>
          <div class="subpanel"><div class="subpanel-title">Timing breakdown · per mob</div><div class="timing-bars">${timingHtml}</div></div>
        </div>
      </div>
      <div class="focus-panel grow">
        <div class="focus-title">Stat Weights</div>
        <div class="focus-subtitle">${weightModel.kind==='equivalent'?`Native per-point weights · ${esc(statRefLabel(weightModel.reference))} = 1.00 · used for gear values`:'Canonical scorer sensitivity · higher is better'}</div>
        <div class="weight-bars">${weightHtml}</div>
        ${statWeightAvailability(row)?`<div class="small muted" style="margin-top:8px">Availability · ${esc(statWeightAvailability(row))}</div>`:''}
        <div class="small muted" style="margin-top:8px">source · ${esc((row.data_sources||[]).join(' + ')||row.source||'unknown')} · row ${esc(row.decision_row_id||'—')}${row.gear_fixed_point?` · gear FP ${esc(row.gear_fixed_point.converged?'converged':'not converged')} ${esc(row.gear_fixed_point.iterations??'—')} iter`:''}</div>
      </div>
    </div>
    <div class="focus-col">
      <div class="focus-panel grow">
        <div class="focus-title">Gear · Level ${lvl}</div>
        <div class="focus-subtitle">${gear.used.length} named items · ${gear.missing.length} catalogue gaps</div>
        ${gearHtml}
        ${gearToolHtml(row,gear)}
        ${coverage?`<div class="coverage-box small"><b>Coverage</b><div class="muted" style="margin-top:3px">${esc(coverage)}</div></div>`:''}
      </div>
      ${focusDecisionContextHtml(row,rr)}
    </div>`;
}
function renderRoute(){const meta=targetMeta(state.cls,state.target),route=meta.routes?.[state.route]||{},rr=data?.spec_regret?.[state.cls]?.targets?.[String(state.target)]?.routes?.[state.route]||{},mat=matrixFor(state.cls,state.target,state.route),rows=routeRows(),build=data?.forever_builds?.[state.cls],nativeContext=genericNativeRouteContext(rows[0]);currentRows=new Map(rows.map(r=>[Number(r.level),r]));const unavailable=routeUnavailableReason();$('routeSummary').textContent=`${state.cls} · ${routeLabel(state.cls,state.route)} → L${state.target} · ${rows.length} per-level decisions${build?.as_of?` · Forever ${build.as_of}${build.source==='legacy_compat_default'?' (legacy snapshot)':''}`:''}; ${state.route==='per_level_best'?'each level may fresh-respec (~1 s) to its fastest searched build; ':''}${unavailable?`unavailable: ${unavailable}; `:''}${nativeContext.proxy?'native proxy weapon/base stats; no named gear; sensitivities measured on proxy; cross-class scores not comparable.':nativeContext.native?'native selected route; gear details on open; bounded fidelity.':'gear is lazy-rendered on open.'}`;$('routeBadges').innerHTML=`${state.route==='unconstrained'?badge('cumulative optimum','opt'):(state.route==='per_level_best'?badge('per-level fastest · respec ~1s','opt'):badge('regret '+(rr.regret_percent==null?'—':Number(rr.regret_percent).toFixed(2)+'%'),Number(rr.regret_percent||0)>5?'warn':'')+badge(rr.constraint_label||routeLabel(state.cls,state.route))+badge(rr.constraint_source||'route_registry'))}${meta.uses_unverified_levels?badge('provisional > L'+(meta.verified_level_cap??'—'),'warn'):''}${meta.planning_status==='provisional_planning_range'?badge('planning ≤ L'+(meta.planning_level_cap??'—')):''}${meta.uses_levels_above_planning_cap?badge('above planning cap L'+(meta.planning_level_cap??'—'),'bad'):''}${mat?.stat_weights_error?badge('stat weight errors','warn'):''}${nativeContext.proxy?badge('proxy · no named gear','warn'):''}`;$('routeLevels').innerHTML=rows.length?rows.map(row=>{const lvl=Number(row.level),focus=lvl===Number(state.level),tal=row.talent_added||row._transition?.changes?.talent_added,sw=statWeightSummary(row);return `<article class="level-card ${focus?'focus':''}" id="route-L${lvl}"><div class="level-top"><div><div class="level-title">L${lvl}${tal?` · <span class="good">+${entityLabel(prettyTalent(tal),talentMeta(row,tal),'talent-icon')}</span>`:''}</div><div class="small">${badge(row.talent_family||state.route)} ${badge(row.combat_profile||'profile —')} ${badge(nativeContext.proxy?'proxy weapon · no named gear':(row.gear||'gear —'))} ${badge('pull '+(row.pull_size??'—'))}</div></div><div class="level-metrics"><b>${mph(row.mobs_per_hour)}</b><div class="small muted">${esc(timingSummary(row))}</div></div></div><div class="changes small">${esc(changeText(row))}${nativeContext.native?` · <button type="button" data-native-route-level="${lvl}" class="native-route-jump">Inspect L${lvl}</button>`:''}</div><div class="allocation"><code>${esc(row.allocation||'—')}</code></div><div class="rowline small"><b>rotation</b> · <code>${esc(row.rotation||row.policy||'—')}</code>${row.aura?` · aura ${esc(row.aura)}`:''}${row.mana_plan?` · mana ${esc(row.mana_plan)}`:''}</div><div class="rowline small weights"><b>${nativeContext.proxy?'proxy stat sensitivity':'stat weights'}</b> · ${esc(sw)}</div><details class="gear-detail" data-level="${lvl}"><summary><b>${nativeContext.proxy?'proxy loadout · no named items':'items used'}</b> · ${esc(gearSummary(row))}</summary><div class="gear-body small muted">Open to load item details.</div></details></article>`}).join(''):`<div class="muted">${esc(unavailable||'No per-level route rows available.')}</div>`;document.querySelectorAll('.gear-detail').forEach(d=>d.addEventListener('toggle',()=>{if(!d.open||d.dataset.loaded)return;const row=currentRows.get(Number(d.dataset.level));d.querySelector('.gear-body').innerHTML=gearDetailsHtml(row);d.dataset.loaded='1';refreshWowheadLinks()}));
  $('routeLevels').onclick=e=>{const b=e.target.closest('button[data-native-route-level]');if(!b)return;const level=Number(b.dataset.nativeRouteLevel);if(!routeRows().some(r=>Number(r.level)===level))return;state.level=level;syncState({allowEmptyClass:true});renderAll()};
  if(nativeContext.native){const html=genericNativeRouteDisclosure(rows.find(x=>Number(x.level)===Number(state.level))||rows[0]);const existing=document.getElementById('nativeRouteScope');if(existing)existing.innerHTML=html;else $('routeSummary').insertAdjacentHTML('afterend', '<div id="nativeRouteScope">'+html+'</div>')}
  else document.getElementById('nativeRouteScope')?.remove();}
function parseTalentRanks(text){const out={};for(const m of String(text||'').matchAll(/([a-zA-Z][a-zA-Z0-9_]*)\s*[:=]\s*(\d+)/g))out[m[1]]=Number(m[2]);return out}
function isTalentsForeverUrl(text){return /^https?:\/\/(?:www\.)?talentsforever\.com\//i.test(String(text||'').trim())}
async function queueContinuationCalculations(){const j=lastContinuation||{},constraint=j.constraint||{},at=Number(j.at_level??constraint.at_level??$('currentLevel').value),target=Number(j.target_level??$('continueTarget').value),box=$('continueResult');if(!constraint.at_level_talent_allocation_exact){box.innerHTML='<div class="continuation-result bad">Cannot queue: exact current allocation is missing.</div>';return}box.innerHTML='<div class="continuation-result muted">Queueing deep canonical recovery search…</div>';try{const payload={ruleset:'forever',class_name:state.cls,start_level:10,end_level:target,objective:'cumulative',endpoint_mode:'smooth',priority:0,deduplicate:true,config:{workers:1,beam_width:128,family_keep:16,final_k:64,stat_weight_top_k:1,continuation_constraint:{at_level:at,at_level_talent_allocation_exact:constraint.at_level_talent_allocation_exact,source:j.current_talents_source||null}}};const r=await fetch('/api/service/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),v=await r.json();if(!r.ok)throw new Error(v.error||`HTTP ${r.status}`);const id=v.job?.job_id||v.job?.id||'created';box.innerHTML=`<div class="continuation-result"><div>${badge('queued','good')} ${badge('canonical deep search','opt')}</div><div class="small muted">L10→L${target} · exact current allocation pinned as recovery metadata at L${at} · job ${esc(id)}</div><div class="small">Continuation remains fail-closed until the new publication contains this corridor. Re-run <b>Find best continuation</b> after the job completes.</div></div>`;setTimeout(refreshService,250)}catch(e){box.innerHTML=`<div class="continuation-result bad">Queue failed: ${esc(e)}</div>`}}
async function runContinuation(){const rawInput=String($('currentTalents').value||'').trim(),at=Number($('currentLevel').value),target=Number($('continueTarget').value),sourceUrl=isTalentsForeverUrl(rawInput)?rawInput:'';const ranks=sourceUrl?{}:parseTalentRanks(rawInput);if(!sourceUrl&&!Object.keys(ranks).length){$('continueResult').innerHTML='<div class="continuation-result bad">No talent ranks found. Paste talent:rank pairs or a TalentsForever build URL.</div>';return}$('continueResult').innerHTML='<div class="continuation-result muted">Resolving exact current allocation and checking preserved frontier…</div>';const constraint={at_level:at};if(!sourceUrl)constraint.at_level_talent_allocation_exact=ranks;try{const r=await fetch('/api/decisions/constraint',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class:state.cls,target_level:target,constraint,source_url:sourceUrl||undefined})}),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);lastContinuation={...j,class:state.cls,target_level:target,at_level:at};const src=j.current_talents_source||{};if(j.status==='available'){const p=j.path||{},c=j.continuation||{},nt=c.next_talent_pick||{},nm=c.next_meaningful_decision||{},uc=j.unrestricted_path||{},ds=j.dual_spec_continuation||{},sw=ds.next_switch||{},srcLine=src.source_url?`<div class="small muted">TalentsForever · ${esc(src.progression_source||'exact')} · ${esc(src.allocation||'')}</div>`:'';$('continueResult').innerHTML=`<div class="continuation-result"><div>${badge('available','good')} ${badge('regret '+Number(j.regret_percent||0).toFixed(2)+'%',Number(j.regret_percent||0)>5?'warn':'')} ${badge('no respec')}</div><div class="small muted">Exact current allocation at L${at} → best preserved continuation to L${target} · ${esc(j.regret_authority||j.authority||'canonical')}</div>${srcLine}${nt.level?`<div><b>Next talent</b> · L${nt.level} · <code>${esc(nt.talent_added||'—')}</code></div>`:'<div class="small muted">No later talent pick in this target window.</div>'}${nm.level?`<div class="small"><b>Next decision</b> · L${nm.level} · ${esc(Object.entries(nm.changes||{}).map(([k,v])=>k+'='+v).join(' · '))}</div>`:''}${sw.level?`<div class="small"><b>Dual-spec plan</b> · switch at L${sw.level} → ${esc(sw.to_route||sw.to_slot||'secondary')} <span class="muted">(level boundary)</span></div>`:''}<div class="allocation"><code>${esc(p.allocation||'—')}</code></div><div>${mph(p.mobs_per_hour)} <span class="small muted">· unrestricted ${mph(uc.mobs_per_hour)}</span></div></div>`}else{const queueable=j.status==='not_preserved_requires_constrained_rerun'&&j.constraint?.at_level_talent_allocation_exact;$('continueResult').innerHTML=`<div class="continuation-result warn"><b>${esc(j.status)}</b><div class="small">${esc(j.note||'No preserved route matches these current talents.')}</div>${src.source_url?`<div class="small muted">Resolved from TalentsForever: ${esc(src.allocation||'')}</div>`:''}${queueable?'<button type="button" id="queueContinuationCalc" style="margin-top:8px">Queue required calculations</button>':''}</div>`;if(queueable)$('queueContinuationCalc').addEventListener('click',queueContinuationCalculations)}renderFocus()}catch(e){lastContinuation={status:'error',class:state.cls,target_level:target,at_level:at,note:String(e)};$('continueResult').innerHTML=`<div class="continuation-result bad">${esc(e)}</div>`;renderFocus()}}
function renderDual(){const rows=Object.entries(data?.dual_spec||{});$('dual').innerHTML=rows.length?rows.map(([cls,d])=>{const a=d.pair?.A,b=d.pair?.B,ph=(d.phases||[]).map(p=>`L${p.start_level}${p.end_level!==p.start_level?'–'+p.end_level:''} ${esc(p.route||p.slot)}`).join(' → ');return `<div class="cmp-card"><b style="color:${classColor(cls)}">${esc(classLabel(cls))}</b><div>${badge(d.status,d.status==='available'?'good':'warn')} ${d.gain_percent==null?'':badge('gain '+Number(d.gain_percent).toFixed(2)+'%')}</div><div class="small muted">unlock L${d.unlock_level??'—'} · target L${d.target_level??'—'} · ${esc(d.reason||'')}</div>${d.status==='available'?`<div class="small"><b>A</b> ${esc(a?.route||'—')} · <b>B</b> ${esc(b?.route||'—')} · primary ${esc(d.primary_before_unlock||'—')}</div><div class="small muted">${ph||'no post-unlock phases'}</div><div class="small">${esc(d.switch_recommendation||'')}</div>`:''}</div>`}).join(''):'<div class="muted">No dual-spec artifact.</div>'}
function renderDiagnostics(){const ep=data?.endpoint_paths?.[state.cls]||{},fid=ep.model_fidelity||{},matrix=fid.capability_matrix||{},specs=Object.entries(matrix).filter(([k])=>k!=='shared');const caps=specs.length?specs.map(([spec,rows])=>`<div style=\"margin-top:4px\"><b>${esc(prettyTalent(spec))}</b> · ${Object.entries(rows||{}).map(([k,v])=>`${esc(prettyTalent(k))}: ${esc(v)}`).join(' · ')}</div>`).join(''):'';$('diagnostics').innerHTML=`${esc(data?.comparability_note||'')}<br>${esc(data?.authority_note||'')}<br><br><b>Fidelity · ${esc(classLabel(state.cls))}</b> · verified ≤L${esc(ep.verified_level_cap??fid.verified_level_cap??'—')} · planning ≤L${esc(ep.planning_level_cap??fid.planning_level_cap??'—')} · ${esc(fid.rating||'unknown')} ${caps}<br><br><b>Design invariant:</b> class, target, route and inspect level are one shared state. No independent mage-only stat selector exists.`}
async function runIceLanceValidation(){
  const panel=$('iceLanceValidationPanel'),box=$('iceLanceValidation');panel.style.display='block';
  if(state.cls!=='mage'){box.innerHTML='<span class="warn">Ice Lance validation is Mage-only.</span>';return;}
  box.innerHTML=`Running bounded L${Number(state.level)} event comparison…`;
  try{
    const r=await fetch('/api/decisions/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class:'mage',level:Number(state.level),question:'ice_lance'})});
    if(!r.ok)throw new Error(await r.text());const v=await r.json(),o=v.optimum||{},il=v.best_ice_lance||{};
    const delta=v.delta_mobs_per_hour==null?null:Number(v.delta_mobs_per_hour),pct=(delta!=null&&Number(o.mobs_per_hour)>0)?100*delta/Number(o.mobs_per_hour):null;
    box.innerHTML=`<div class="cmp"><div class="cmp-card"><b>Event optimum · L${v.level}</b><div class="kpi good">${mph(o.mobs_per_hour)}</div><div class="small">${esc(o.rotation||'—')}</div><code class="small">${esc(o.allocation||'—')}</code></div><div class="cmp-card"><b>Best Ice Lance challenger</b><div class="kpi ${v.ice_lance_is_optimum?'good':''}">${mph(il.mobs_per_hour)}</div><div class="small">${esc(il.rotation||'—')}</div><code class="small">${esc(il.allocation||'—')}</code></div></div><div class="small ${delta!=null&&delta<0?'warn':'good'}" style="margin-top:8px">Ice Lance Δ ${delta==null?'—':(delta>=0?'+':'')+delta.toFixed(2)+' mobs/h'}${pct==null?'':` (${pct>=0?'+':''}${pct.toFixed(2)}%)`} · ${esc(v.candidate_count)} retained candidates · n=${esc(v.event_samples)} · ${esc(v.authority||'')}</div>`;
  }catch(e){box.innerHTML=`<span class="bad">Validation failed: ${esc(e)}</span>`}
}
function syncClassSpecificControls(){const mage=state.cls==='mage',button=$('validateIceLance'),panel=$('iceLanceValidationPanel');if(button){button.style.display=mage?'':'none';button.disabled=!mage}if(panel&&!mage){panel.style.display='none';$('iceLanceValidation').innerHTML=''}}
function genericActionSummary(a){const costs=(a?.costs||[]).map(c=>`${Number(c.amount??0)} ${esc(c.resource_id||'resource')}`).join(' + '),fx=(a?.effects||[]).find(e=>String(e.effect_type||'')==='damage'),dot=(a?.effects||[]).find(e=>String(e.effect_type||'')==='periodic_damage'),heal=(a?.effects||[]).find(e=>String(e.effect_type||'')==='heal'),hot=(a?.effects||[]).find(e=>String(e.effect_type||'')==='periodic_heal'),mode=(a?.effects||[]).find(e=>String(e.effect_type||'')==='mode_change'),parts=[esc(a?.name||a?.id||'action')];if(a?.cast_time_s!=null)parts.push(`cast ${Number(a.cast_time_s).toFixed(1)}s`);if(a?.gcd_s!=null)parts.push(`GCD ${Number(a.gcd_s).toFixed(1)}s`);if(costs)parts.push(costs);if(fx){parts.push(`${Number(fx.base_min??0)}–${Number(fx.base_max??0)} ${esc(fx.school||'damage')}`);const traces=Object.values(fx.field_provenance||{}),tuned=traces.some(rows=>(rows||[]).some(x=>x?.stage==='overlay')),approx=(fx.unsupported_semantics||[]).some(x=>x?.status==='explicit_approximation');if(tuned)parts.push('dated tuning');if(approx)parts.push('≈ source magnitude')}if(dot)parts.push(`${Number(dot.total_base_damage??0)} periodic / ${Number(dot.duration_s??0).toFixed(0)}s · tick ${Number(dot.tick_interval_s??0).toFixed(0)}s · ${esc(dot.refresh_rule||'refresh')}`);if(heal)parts.push(`${Number(heal.base_min??0)}–${Number(heal.base_max??0)} heal`);if(hot)parts.push(`${Number(hot.total_base_heal??0)} periodic heal / ${Number(hot.duration_s??0).toFixed(0)}s · tick ${Number(hot.tick_interval_s??0).toFixed(0)}s · ${esc(hot.refresh_rule||'refresh')}`);if(mode)parts.push(`mode → ${esc(mode.target_mode_id||'—')}`);return parts.join(' · ')}
function genericActorStateSummary(a){const stats=Object.entries(a?.base_stats||{});const body=stats.length?stats.map(([k,v])=>`${esc(prettyTalent(k))} ${Number(v)}`).join(' · '):'no source-backed base stats';return `${esc(a?.id||'actor')} · ${body}`}
function genericResourceStateSummary(r){const name=esc(r?.name||r?.id||'resource'),initial=r?.initial_amount,capacity=r?.capacity,regen=Number(r?.regeneration_per_s||0),regenText=regen>0?` · +${regen.toFixed(1)}/s`:'';if(initial==null&&capacity==null)return `${name} · definition only${regenText}`;if(initial!=null&&capacity!=null)return `${name} ${Number(initial)}/${Number(capacity)}${regenText}`;return `${name} · capacity ${capacity==null?'—':Number(capacity)}${regenText}`}
function genericModeSummary(r){const modes=Array.isArray(r?.modes)?r.modes:[],probe=r?.provenance?.mode_runtime_probe;if(!modes.length)return '';const rows=modes.map(m=>{const mods=(m.stat_modifiers||[]).map(x=>x.kind==='add_stat_scaled'?`${esc(x.target_stat)} + ${Number(x.value||0)}×${esc(x.source_stat||'stat')}`:`${esc(x.target_stat)} +${Number(x.value||0)}`).join(', '),resources=(m.resource_rules||[]).map(x=>`${esc(x.resource_id)} ${x.active===false?'off':'on'} · ${esc(x.on_enter||'preserve')}`).join(' · '),actions=Array.isArray(m.enabled_action_ids)?`${m.enabled_action_ids.length} enabled actions`:'unrestricted actions';return `${m.initial?'★ ':''}${esc(m.label||m.id)} · ${actions}${mods?` · ${mods}`:''}${resources?` · ${resources}`:''}`}).join('<br>');const transition=probe?`${esc(probe.initial_mode_id||'—')} → ${esc(probe.entered_mode_id||'—')} → ${esc(probe.final_mode_id||'—')}`:'not executed',ap0=probe?.initial_stats?.attack_power,ap1=probe?.entered_stats?.attack_power,energy0=probe?.initial_resource_active?.energy,energy1=probe?.entered_resource_active?.energy;return `<div class="coverage-box small"><b>Generic Mode runtime</b><div style="margin-top:4px">${rows}</div><div class="muted">transition ${transition}${ap1==null?'':` · AP ${Number(ap0||0).toFixed(0)}→${Number(ap1).toFixed(0)}`}${energy1==null?'':` · Energy ${energy0?'on':'off'}→${energy1?'on':'off'}`}${probe?.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}
function genericEnergySummary(r){const probe=r?.provenance?.energy_runtime_probe,res=(r?.resources||[]).find(x=>x?.id==='energy'),claw=(r?.actions||[]).find(x=>x?.family_key==='claw');if(!probe&&!res&&!claw)return '';const times=(probe?.claw_times_s||[]).map(x=>Number(x).toFixed(2)).join(' / '),before=(probe?.energy_before||[]).map(x=>Number(x).toFixed(0)).join(' / '),after=(probe?.energy_after||[]).map(x=>Number(x).toFixed(0)).join(' / ');return `<div class="coverage-box small"><b>Generic Energy + Cat action gating</b><div style="margin-top:4px">${res?`Energy ${Number(res.initial_amount||0).toFixed(0)}/${Number(res.capacity||0).toFixed(0)} · +${Number(res.regeneration_per_s||0).toFixed(1)}/s`:''}${claw?` · ${esc(claw.name||'Claw')} ${Number(claw.costs?.[0]?.amount||0).toFixed(0)} Energy`:''}</div><div class="muted">${probe?`Claw t=${times}s · Energy before ${before} → after ${after} · blocked @ ${Number(probe.blocked_time_s||0).toFixed(2)}s with ${Number(probe.blocked_energy||0).toFixed(0)} · third legal after regen ${probe.third_eligible_after_regen?'yes':'no'} · ${Number(probe.claw_damage_events||0)} real weapon-damage events`: 'not executed'}${probe?.combo_points_target_bound_g26?' · combo points target-bound':''}${probe?.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}

function genericComboPointSummary(r){const probe=r?.provenance?.combo_point_policy_probe,res=(r?.resources||[]).find(x=>x?.id==='combo_points'),rip=(r?.actions||[]).find(x=>x?.family_key==='rip');if(!probe&&!res&&!rip)return '';const threshold=probe?.selected_combo_point_threshold,selected=probe?.selected_action_ids||[],rows=(probe?.threshold_results||[]).filter(x=>x.combo_point_threshold!=null).sort((a,b)=>Number(a.combo_point_threshold)-Number(b.combo_point_threshold));const bestByCp=[];for(const row of rows){const cp=Number(row.combo_point_threshold),old=bestByCp.find(x=>x.cp===cp);if(!old||Number(row.seconds_per_mob)<old.s) {if(old){old.s=Number(row.seconds_per_mob)}else bestByCp.push({cp,s:Number(row.seconds_per_mob)})}}const curve=bestByCp.map(x=>`${x.cp}CP ${x.s.toFixed(2)}s`).join(' · ');return `<div class="coverage-box small"><b>Generic target-bound combo points + finisher search</b><div style="margin-top:4px">${res?`Combo Points ${Number(res.initial_amount||0).toFixed(0)}/${Number(res.capacity||0).toFixed(0)} · target-bound`:''}${rip?` · ${esc(rip.name||'finisher')}`:''}</div><div class="muted">${probe?`selected ${esc(probe.selected_candidate_id||'—')} · ${threshold==null?'no finisher threshold':Number(threshold).toFixed(0)+' CP threshold'} · ${Number(probe.selected_seconds_per_mob||0).toFixed(2)}s · actions ${selected.map(esc).join(' → ')}`:'not executed'}${curve?`<br>threshold curve · ${curve}`:''}${probe?.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}

function genericEventResourceSummary(r){const probe=r?.provenance?.event_resource_gain_probe,res=(r?.resources||[]).find(x=>x?.id===probe?.resource_id)||(r?.resources||[]).find(x=>x?.event_gain_rules?.length);if(!probe&&!res)return '';const rule=res?.event_gain_rules?.[0]||{};return `<div class="coverage-box small"><b>Generic event-driven Rage</b><div style="margin-top:4px">${res?`${esc(res.name||res.id)} ${Number(res.initial_amount||0).toFixed(0)}/${Number(res.capacity||0).toFixed(0)} · ${esc(rule.event_kind||'event')} × ${Number(rule.multiplier||0).toFixed(5)}`:''}</div><div class="muted">${probe?`mechanics probe ${Number(probe.resource_before||0).toFixed(0)} → ${Number(probe.resource_after_gain||0).toFixed(0)} · ${Number(probe.spender_cost||0).toFixed(0)}-Rage spender ${probe.spender_eligible_before_gain?'already legal':'blocked before'} → ${probe.spender_eligible_after_gain?'legal after gain':'still blocked'} · after spend ${Number(probe.resource_after_spend||0).toFixed(0)}`:'not executed'}${rule?.metadata?.raw_incoming_conversion==='deferred_to_g28'?'<br>raw incoming / Armor → Rage-basis conversion deferred to G28':''}${probe?.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}
function genericIncomingDamageSummary(r){const p=r?.provenance?.incoming_damage_probe;if(!p)return '';const z=p.zero_armor||{},h=p.high_armor||{};return `<div class="coverage-box small"><b>Generic incoming damage + mitigation</b><div style="margin-top:4px">${esc(p.incoming_attack_id||'incoming attack')} · raw ${Number(p.raw_damage||0).toFixed(2)} · ${esc(p.mitigation_rule_id||'no mitigation rule')}</div><div class="muted">0 Armor: ${Number(z.health_damage||0).toFixed(2)} HP loss · 1000 Armor: ${Number(h.health_damage||0).toFixed(2)} HP loss · reduction ${Number(h?.resolved?.armor_reduction||0).toFixed(3)}<br>Rage basis ${esc(p.projection_source_value_field||'—')} × ${Number(p.projection_multiplier||0).toFixed(2)} · Rage ${Number(z.rage_gained||0).toFixed(3)} / ${Number(h.rage_gained||0).toFixed(3)}${p.rage_basis_independent_of_real_armor?' · real Armor affects survivability, not Forever Rage basis':''}${p.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}
function genericHunterPetSummary(r){const p=r?.provenance?.hunter_pet_policy_probe;if(!p||p.status!=='executed'||String(r?.identity?.class_name||'').toLowerCase()!=='hunter')return '';const policy=(p.selected_policy||[]).map(x=>esc(x)).join(' → ')||'auto-only',candidate=(p.pet_policy_candidates||[]).map(x=>`${esc((x.policy||[]).join(' → ')||'auto')} ${x.kill_s==null?'no kill':Number(x.kill_s).toFixed(2)+'s'}`).join(' · '),d=p.selected_detail||{},mods=p.modifiers||[],inherit=mods.filter(x=>x.target_actor_id!==x.source_actor_id).map(x=>`${esc(x.target_stat_id||'stat')} ${Number(x.before||0).toFixed(2)}→${Number(x.after||0).toFixed(2)}`).join(' · ');return `<div class="coverage-box small"><b>Hunter + Cat pet · executable G35 slice</b><div style="margin-top:4px">L${esc(p.level)} · owner-only ${Number(p.owner_only_kill_s||0).toFixed(2)}s → owner+pet ${Number(p.owner_plus_pet_policy_kill_s||0).toFixed(2)}s · selected <b>${policy}</b></div><div class="muted">5 policy candidates · ${candidate}<br>${inherit} · Focus regen ${Number(p.focus_regen_per_s||0).toFixed(1)}/s · ${esc((d.action_events||[]).length)} pet actions started<br><b>Bounded scenario, not a complete leveling score:</b> sourced Bite/Claw ranks &amp; scaling; ranged weapon input, natural pet DPS curve, hit assumptions are provisional. Threat/positioning, pet survivability and talent-route completeness remain unsupported. Legacy fallback disabled.</div></div>`}
function genericShamanSummary(r){const p=r?.provenance?.shaman_generic_decision;if(!p||p.status!=='executed'||String(r?.identity?.class_name||'').toLowerCase()!=='shaman')return '';const acts=(p.executed_action_ids||[]).map(esc).join(' → ');return `<div class="coverage-box small"><b>Generic Shaman · hybrid + Rockbiter + Searing Totem · G42</b><div style="margin-top:4px">L${esc(p.level)} · ${Number(p.seconds_per_mob).toFixed(2)} s/mob · white ${Number(p.white_damage).toFixed(1)} (${Number(p.white_swings)} swings) · Searing Totem ${Number(p.searing_totem_damage||0).toFixed(1)} (${Number(p.searing_totem_swings||0)} bolts) · Earth Shock ${Number(p.shock_damage).toFixed(1)} · Lightning Bolt ${Number(p.lightning_damage).toFixed(1)}</div><div>Imbue ${esc(p.rockbiter_rank)} · +${Number(p.rockbiter_ap_bonus).toFixed(0)} AP · executed: ${acts}</div><div class="muted"><b>Bounded L10–20 proxy, NOT leveling advice.</b> Rockbiter occupies a single Mode slot in this proof; simultaneous stances, 60-minute expiration, canonical gear, hit/resists, higher ranks and full talent/route optimization remain unresolved. Searing Totem range/placement and attack cadence are approximated (2s proxy), not PvP-fidelity. No class-specific scorer.</div></div>`}
function genericPriestSummary(r){const p=r?.provenance?.priest_generic_decision;if(!p||p.status!=='executed'||String(r?.identity?.class_name||'').toLowerCase()!=='priest')return '';const actions=(p.executed_action_ids||[]).map(esc).join(' → ')||'wand only';return `<div class="coverage-box small"><b>Generic Priest · caster + ranged wand · G40</b><div style="margin-top:4px">L${esc(p.level)} · ${Number(p.selected_seconds_per_mob).toFixed(2)} s/mob · wand ${Number(p.wand_damage).toFixed(1)} damage (${Number(p.wand_swing_count)} swings) · Smite ${Number(p.smite_damage).toFixed(1)} · DoT ${Number(p.dot_damage).toFixed(1)}</div><div>Executed spells: ${actions}</div><div class="muted"><b>Bounded L10–20 proof, NOT leveling advice.</b> Spell ranks are sourced from Forever; wand DPS/speed, Mana/Spirit and hit outcomes are explicit scenario proxies. Spell resists, DoT crit, incoming healing policy, talents, gear and travel remain unresolved. No legacy fallback.</div></div>`}
function genericRogueSummary(r){const p=r?.provenance?.rogue_generic_decision;if(!p||p.status!=='executed'||String(r?.identity?.class_name||'').toLowerCase()!=='rogue')return '';const acts=(p.selected_executed_action_ids||[]).map(x=>esc(x)).join(' → ')||'white autoattacks',snap=(p.finisher_resource_snapshots||[]).map((cp,i)=>`${Number(cp)} CP → ${Number((p.finisher_damage||[])[i]||0).toFixed(1)} damage`).join(' · ')||'no finisher used',delta=p.improvement_s==null?'n/a':Number(p.improvement_s).toFixed(2);return `<div class="coverage-box small"><b>Generic Rogue · Energy / Combo Points / Eviscerate · G38</b><div style="margin-top:4px">L${esc(p.level)} · selected <b>${Number(p.selected_seconds_per_mob).toFixed(2)} s/mob</b> vs seed ${p.seed_seconds_per_mob==null?'n/a':Number(p.seed_seconds_per_mob).toFixed(2)+' s/mob'} · improvement ${delta}s · selected finisher threshold ${p.selected_combo_point_threshold??'n/a'} CP</div><div>Executed: <b>${acts}</b></div><div>Real finisher snapshots: ${snap} · CP consumption events ${Number(p.finisher_resource_consumption_events||0)}</div><div class="muted"><b>Bounded L10–20 combat/recovery scenario, not final leveling advice.</b> Sinister Strike / Eviscerate ranks are from Forever tooltips; mainhand AP/DPS/speed, hit/crit and continuous average Energy are qualified model assumptions. Eviscerate AP scaling, stealth positioning, offhand, talent/gear/route and travel remain unresolved. No legacy fallback.</div></div>`}
function genericWarriorSummary(r){const p=r?.provenance?.warrior_generic_decision;if(!p||p.status!=='executed'||String(r?.identity?.class_name||'').toLowerCase()!=='warrior')return '';const done=p.selected_executed_action_ids||[],declared=p.selected_declared_rule_action_ids||[],seed=p.seed_executed_action_ids||[],actual=done.length?done.map(x=>esc(x)).join(' → '):(p.selected_auto_attack_only?'Auto Attack only':'none'),seedActual=seed.map(x=>esc(x)).join(' → ')||'Auto Attack only',delta=Number(p.improvement_s||0);return `<div class="coverage-box small"><b>Generic Warrior · Rage / stances / auto policy · G37</b><div style="margin-top:4px">L${esc(p.level)} · selected <b>${Number(p.selected_seconds_per_mob).toFixed(2)} s/mob</b> vs seed ${Number(p.seed_seconds_per_mob).toFixed(2)} s/mob · improvement ${delta.toFixed(2)}s</div><div>Executed: <b>${actual}</b> · seed executed: ${seedActual}</div><div class="muted">Policy priorities (not necessarily executed): ${declared.map(x=>esc(x)).join(' → ')||'none'} · ${Number(p.selected_rage_gain_events||0)} real white-hit Rage events (${Number(p.selected_rage_gained||0).toFixed(2)} Rage)<br><b>Bounded L10–20 combat/recovery scenario, not final leveling advice:</b> source-backed Bloodrage, Rend, Thunder Clap and stances; weapon/AP/HP are qualified proxies. Heroic Strike next-swing replacement, incoming Rage, full talents/gear and travel remain unresolved. Legacy fallback disabled.</div></div>`}
function genericTimedSummonSummary(r){const p=r?.provenance?.timed_summon_runtime_probe;if(!p||p.status!=='executed')return '';const by=p.damage_by_role||{},lc=p.lifecycle||[],lifecycle=lc.map(x=>`${esc(x.kind==='SummonSpawn'?'spawn':'despawn')} ${Number(x.time_s).toFixed(1)}s`).join(' → ');return `<div class="coverage-box small"><b>Generic timed summon &amp; damage attribution · G36 engine proof</b><div style="margin-top:4px">${lifecycle} · source lifetime ${Number(p.duration_s).toFixed(1)}s</div><div class="small">Player ${Number(by.player||0).toFixed(1)} · persistent pet ${Number(by.pet||0).toFixed(1)} · summon ${Number(by.summon||0).toFixed(1)} damage · total ${Number(p.with_summon_damage||0).toFixed(1)} vs without summon ${Number(p.baseline_damage||0).toFixed(1)}</div><div class="muted">Expired summons cannot swing or complete casts; ${(p.skipped_after_despawn||[]).length} cancelled events in trace. <b>Forever spell supplies duration only</b>; summon damage is synthetic and player availability / exact count are not verified. Not a leveling score. ${p.legacy_fallback===false?'Legacy fallback disabled.':''}</div></div>`}
function genericMultiActorSummary(r){const p=r?.provenance?.multi_actor_runtime_probe;if(!p||p.status!=='executed')return '';const a=p.actor_damage||{},actors=p.actor_ids||[],rows=actors.map(id=>`${esc(id)} ${Number(a[id]||0).toFixed(1)} damage`).join(' · ');return `<div class="coverage-box small"><b>Generic multi-Actor event queue · engine proof</b><div style="margin-top:4px">${esc(rows)} · one shared target · kill ${Number(p.baseline_kill_s||0).toFixed(2)}s → ${Number(p.companion_kill_s||0).toFixed(2)}s</div><div class="muted">Independent resources/GCD/cooldowns + simultaneous actions/autoattacks. <b>Synthetic mechanics fixture</b>; no class pet tuning or Hunter policy claim. ${p.legacy_fallback===false?'Legacy fallback disabled.':''}</div></div>`}
function genericEventTriggerSummary(r){const p=r?.provenance?.event_trigger_damage_probe;if(!p||p.status!=='executed')return '';const eff=p.effect||{};return `<div class="coverage-box small"><b>Generic event trigger · ${esc(p.trigger_name||p.trigger_id||'trigger')}</b><div style="margin-top:4px">${esc(p.event_kind||'event')} → ${Number(eff.base_min||0).toFixed(0)} ${esc(eff.school||'')} damage · fired ${Number(p.trigger_count||0)}× · ${Number(p.trigger_damage||0).toFixed(1)} damage</div><div class="muted">timing proof ${Number(p.baseline_seconds_per_mob||0).toFixed(2)}s → ${Number(p.trigger_seconds_per_mob||0).toFixed(2)}s · improvement ${Number(p.improvement_seconds_per_mob||0).toFixed(2)}s${p.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}
function genericModeActionPolicySummary(r){const p=r?.provenance?.mode_action_policy_probe;if(!p)return '';const s=p.policy_search||{},selected=p.selected_policy||{};return `<div class="coverage-box small"><b>Generic mode action policy</b><div style="margin-top:4px">${esc(p.mode_id||'mode')} · ${Number(p.selected_seconds_per_mob||0).toFixed(2)}s/mob · ${esc(p.selected_candidate_id||'—')}</div><div class="muted">seed ${p.seed_seconds_per_mob==null?'—':Number(p.seed_seconds_per_mob).toFixed(2)+'s'} · improvement ${p.improvement_vs_seed_seconds_per_mob==null?'—':Number(p.improvement_vs_seed_seconds_per_mob).toFixed(2)+'s'} · ${Number(s.valid_candidate_count||0)}/${Number(s.candidate_count||0)} valid candidates<br>${esc((p.selected_action_ids||[]).join(' → ')||selected.label||'no selected actions')}${p.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}

function genericCrossModePolicySummary(r){const p=r?.provenance?.cross_mode_policy_probe;if(!p)return '';const path=(p.cross_mode_transitions||[]).map((x,i)=>i===0?`${esc(x.from_mode_id||'—')} → ${esc(x.to_mode_id||'—')}`:`→ ${esc(x.to_mode_id||'—')}`).join(' ');return `<div class="coverage-box small"><b>Cross-mode policy search</b><div style="margin-top:4px">selected ${esc(p.selected_candidate_kind||'—')} · ${Number(p.selected_seconds_per_mob||0).toFixed(2)}s/mob</div><div class="muted">cross-mode ${p.cross_mode_seconds_per_mob==null?'—':Number(p.cross_mode_seconds_per_mob).toFixed(2)+'s'} · Δ ${p.cross_mode_delta_vs_selected_seconds_per_mob==null?'—':Number(p.cross_mode_delta_vs_selected_seconds_per_mob).toFixed(2)+'s'} · ${Number(p.valid_candidate_count||0)}/${Number(p.candidate_count||0)} valid<br>${path||'no transition path'}${p.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}
function genericAutoAttackSummary(r){const autos=(r?.actions||[]).filter(x=>x?.kind==='auto_attack'),probe=r?.provenance?.auto_attack_runtime_probe;if(!autos.length)return '';const rows=autos.map(a=>{const src=a.damage_source||{},dps=Number(src.flat_dps||0),ap=src.attack_power_stat_id?` + ${esc(src.attack_power_stat_id)}/${Number(src.attack_power_per_dps||14)}`:'';return `${esc(a.name||a.id)} · ${Number(a.swing_time_s||0).toFixed(2)}s swing · ${esc(src.kind||'damage source')} ${dps.toFixed(2)} dps${ap} · mode ${esc(a.required_mode_id||'any')}`}).join('<br>');const outcome=probe?.first_outcome||{},w=outcome.outcome_weights||{};return `<div class="coverage-box small"><b>Generic AutoAttack runtime</b><div style="margin-top:4px">${rows}</div><div class="muted">${probe?`${Number(probe.swing_count||0)} swings · ${Number(probe.auto_attack_damage||0).toFixed(2)} damage · first ${Number(probe.first_swing_s||0).toFixed(2)}s${probe.first_swing_during_gcd?' during GCD':''} · outcome miss ${Number(w.miss||0).toFixed(2)} / hit ${Number(w.hit||0).toFixed(2)} / crit ${Number(w.crit||0).toFixed(2)}`:'not executed'}${probe?.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}
function genericRuntimeSummary(r){const rt=r?.provenance?.runtime_execution,seq=r?.provenance?.runtime_sequence,probe=r?.provenance?.runtime_probe;if(!rt)return '';const events=(rt.events||[]).map(x=>esc(x.kind||'event')).join(' → '),death=rt.target_death_s==null?'survives':`death ${Number(rt.target_death_s).toFixed(2)}s`,costsApplied=probe?.resource_costs_applied===true?'cost applied':'cost not applied',manaBefore=seq?.resources_before?.mana,manaAfter=seq?.resources_after?.mana,sequence=seq?`<div class="muted">state progression · ${Number(seq.completed_casts||0)}/${Number(seq.requested_casts||0)} casts · ${manaBefore==null?'resource':`Mana ${Number(manaBefore).toFixed(0)}→${Number(manaAfter).toFixed(0)}`} · t=${Number(seq.end_time_s||0).toFixed(2)}s · GCD/cooldown ready</div>`:'';return `<div class="coverage-box small"><b>Generic event runtime</b><div style="margin-top:4px">${esc(rt.action_id||'action')} · ${Number(rt.total_damage||0).toFixed(2)} damage · target ${Number(rt.target_start_health||0).toFixed(2)}→${Number(rt.target_end_health||0).toFixed(2)} · ${death}</div><div class="muted">${events} · ${esc(rt.damage_resolution||'—')} · ${esc(probe?.target_source_status||'target')} · ${costsApplied}</div>${sequence}</div>`}
function genericPeriodicRuntimeSummary(r){const rt=r?.provenance?.periodic_runtime,probe=r?.provenance?.periodic_runtime_probe;if(!rt)return '';const kinds=(rt.events||[]).map(x=>x.kind||'event'),flow=[...new Set(kinds.filter(x=>['AuraApplied','AuraReplaced','PeriodicTick','AuraExpired','TargetDied'].includes(x)))].map(esc).join(' → '),mana0=rt?.resources_before?.mana,mana1=rt?.resources_after?.mana;return `<div class="coverage-box small"><b>Generic Aura / PeriodicEffect runtime</b><div style="margin-top:4px">${esc(probe?.action_id||'periodic action')} · direct ${Number(rt.direct_damage||0).toFixed(2)} + periodic ${Number(rt.periodic_damage||0).toFixed(2)} · ${Number(rt.periodic_tick_count||0)} landed ticks</div><div class="muted">Aura apply ${Number(rt.aura_applied_count||0)} · replace ${Number(rt.aura_replaced_count||0)} · refresh probe t=${Number(probe?.refresh_at_s||0).toFixed(1)}s · ${flow||'periodic events'}${mana0==null?'':` · Mana ${Number(mana0).toFixed(0)}→${Number(mana1).toFixed(0)}`}</div></div>`}
function genericHealingRuntimeSummary(r){const h=r?.provenance?.healing_runtime_probe;if(!h)return '';const d=h.direct||null,p=h.periodic||null;if(!d&&!p)return '';const direct=d?`${esc(d.action_id||'direct heal')} · HP after ${Number(d.health_after||0).toFixed(0)} · ${Number((d.events||[]).length)} heal event${Number((d.events||[]).length)===1?'':'s'}`:'',hot=p?`${esc(p.action_id||'periodic heal')} · HP after ${Number(p.health_after||0).toFixed(0)} · ${Number((p.heal_events||[]).length)} ticks · ${(p.aura_events||[]).map(x=>esc(x.kind||'aura')).join(' → ')}`:'';return `<div class="coverage-box small"><b>Generic Heal / HoT runtime</b>${direct?`<div style="margin-top:4px">${direct}</div>`:''}${hot?`<div class="muted">${hot}</div>`:''}</div>`}

function genericTalentSummary(r){const t=r?.talents||{},ranks=t.ranks||{},defs=Array.isArray(t.definitions)?t.definitions:[],mods=Array.isArray(t.applied_modifiers)?t.applied_modifiers:[],cmp=t.evaluation_comparison||{},joint=t.joint_search_comparison||{},search=t.search||{};if(!defs.length)return '';const selected=Object.entries(ranks).filter(([,rank])=>Number(rank)>0).map(([id,rank])=>`${esc(defs.find(x=>x.id===id)?.name||id)} ${Number(rank)}`).join(' · ')||'no points';const modText=mods.map(x=>`${esc(x.kind||'modifier')} ${Number(x.before??0)}→${Number(x.after??0)}`).join(' · ');const delta=cmp.delta_seconds_per_mob,selectedPolicy=search?.selected_detail?.policy_candidate_id||search?.selected_detail?.policy_id||'—',jointDelta=joint.delta_seconds_per_mob,searchText=t.search_performed===true?`joint talent + policy search · ${esc(search.candidate_count??'—')} talent candidates · ${esc((search.executable_talent_ids||[]).length)} executable families · selected ${esc(search.selected_candidate_id||'—')} · policy ${esc(selectedPolicy)}${jointDelta==null?'':` · ${Number(jointDelta).toFixed(2)}s/mob vs no talents`}`:t.search_performed===false?'explicit source-backed seed · talent search not yet run':'talent definitions only';return `<div class="coverage-box small"><b>Generic Talent IR</b><div style="margin-top:4px">${selected} · ${Number(t.spent_points||0)}/${Number(t.available_points||0)} points</div>${modText?`<div class="muted">${modText}</div>`:''}${delta==null?'':`<div class="muted">fixed-seed talent delta · ${Number(cmp.baseline_seconds_per_mob||0).toFixed(2)}s → ${Number(cmp.selected_seconds_per_mob||0).toFixed(2)}s · ${Number(delta).toFixed(2)}s/mob</div>`}<div class="muted">${searchText}</div></div>`}
function genericFrontierSummary(r){const gf=data?.generic_frontiers||{},fronts=Array.isArray(gf.frontiers)?gf.frontiers:[];if(!fronts.length||String(gf.class_name||'').toLowerCase()!==String(r?.identity?.class_name||'').toLowerCase())return '';const levels=fronts.map(x=>Number(x.level)).filter(Number.isFinite),cur=fronts.find(x=>Number(x.level)===Number(r?.identity?.level))||fronts[0],winner=cur?.winner||{},range=levels.length?`L${Math.min(...levels)}–${Math.max(...levels)}`:'bounded slice';return `<div class="coverage-box small"><b>Generic LevelFrontier</b><div style="margin-top:4px">${esc(range)} · ${Number(gf.candidate_count||0)} scored candidates · ${Number(cur?.candidate_count||0)} retained at L${esc(cur?.level??'—')}</div><div class="muted">winner ${esc(winner.talent_candidate_id||'—')} · ${winner.seconds_per_mob==null?'—':Number(winner.seconds_per_mob).toFixed(3)+'s/mob'} · authority ${esc(gf.authority||'CandidateResult/LevelFrontier')}</div><div class="muted">route solving ${gf.route_solving===true?'enabled':'gated'} · ${esc(gf.route_blocker||'')}${gf.legacy_fallback===false?' · legacy fallback disabled':''}</div></div>`}

function genericPlayableDruidStepSummary(){
  if(String(data?.active_backend)!=='generic'||String(state.cls).toLowerCase()!=='druid')return '';
  const row=currentFocusRow();
  if(!row||row?.decision_contract?.backend?.id!=='generic')return '';
  const gearCount=Object.keys(row?.gear_stats?.slots||{}).length;
  const warning=(row.quality_warnings||[]).map(esc).join(' · ');
  const weights=statWeightSummary(row);
  return `<div class="coverage-box small"><b>Playable generic Druid · selected L${esc(row.level)}</b><div style="margin-top:4px"><b>${mph(row.mobs_per_hour)}</b> · ${Number(row.seconds_per_mob).toFixed(3)}s/mob · ${esc(row.rotation||row.policy||'policy unavailable')} · ${gearCount} named gear slots</div><div class="muted">${esc(weights)} · native ${esc(row.source||'route DP')} · legacy fallback disabled</div><div class="muted">${warning?'Fixed-point warning: '+warning+' · ':''}Expected-value caster model; travel and full attack-table unresolved. L15+ not route-ready.</div></div>`;
}
function genericNativeRouteContext(row){
  // One backend-neutral route UI for every registered native generic class.
  // Scenario-proxy evidence is explicitly distinct from named-gear optimization.
  if(String(data?.active_backend)!=='generic')return {native:false,proxy:false,route:{}};
  const route=data?.generic_class_routes?.[state.cls]||{};
  const method=String(row?.gear_stats?.selection_method||'');
  const proxy=method==='explicit_scenario_proxy_not_named_gear'||String(route.route_scope||'').includes('weapon_proxy');
  return {native:route.route_solving===true,proxy,route};
}
function genericNativeRouteDisclosure(row){
  const ctx=genericNativeRouteContext(row);
  if(!ctx.native)return '';
  const route=ctx.route,levels=route.levels||[],span=levels.length?`L${esc(Math.min(...levels))}–L${esc(Math.max(...levels))}`:'bounded corridor';
  const warnings=[...new Set([...(route.quality_warnings||[]),...(row?.quality_warnings||[])])];
  const source=ctx.proxy?'Scenario proxy: weapon/base stats, no named gear. Stat sensitivities are measured on the proxy, not transferable item weights. Cross-class scores are not comparable.':'Native selected route with named-gear snapshots; bounded corridor only, not full leveling fidelity.';
  return `<div class="coverage-box small"><b>Native generic route · ${span}</b><div class="muted">${esc(source)}</div>${warnings.length?`<div class="warn">Limits: ${esc(warnings.join(' · '))}</div>`:''}</div>`;
}
function genericRouteSummary(r){const cls=String(r?.identity?.class_name||'').toLowerCase(),gr=data?.generic_class_routes?.[cls]||data?.generic_routes||{};if(!gr.route_solving||String(gr.class_name||'').toLowerCase()!==String(r?.identity?.class_name||'').toLowerCase())return '';const p=gr.path||{},steps=Array.isArray(p.steps)?p.steps:[],range=(gr.levels||[]).length?`L${Math.min(...gr.levels.map(Number))}–L${Math.max(...gr.levels.map(Number))}`:'bounded corridor',cont=steps.map(x=>`L${esc(x.level)} ${esc(x.allocation||'—')}${x.talent_added?' (+'+esc(x.talent_added)+')':''}`).join(' → '),reg=gr.regret||{};return `<div class="coverage-box small"><b>Generic route solve</b><div style="margin-top:4px">${esc(range)} · endpoint L${esc(gr.target_level??'—')} · ${esc(p.allocation||'—')}</div><div class="muted">${cont||'no path'}<br>regret ${reg.regret_percent==null?'—':Number(reg.regret_percent).toFixed(2)+'%'} · authority ${esc(gr.authority||'canonical route DP')}${gr.legacy_fallback===false?' · legacy fallback disabled':''}</div><div class="muted">normal route ${gr.normal_route_selectable===true?'selectable':'blocked'} · ${Number(gr.normal_route_step_count||0)} native scored steps · ${esc((gr.quality_warnings||[]).join(', ')||'no fixed-point warning')}</div><div class="muted">above L${esc(gr.route_blocker_above_level??'—')}: ${esc(gr.route_blocker||'not route-ready')}</div></div>`}
function genericGearStatSummary(r){const g=r?.gear||{},sw=r?.stat_weights||{},fp=g.fixed_point||{};if(g.status!=='selected_named_catalogue_gear'&&!Object.keys(sw).length)return '';const a=g.aggregate_stats||{},ranked=Array.isArray(sw.ranked)?sw.ranked:[],items=Object.values(g.slots||{}),itemNames=items.slice(0,8).map(x=>esc(x?.name||'item')).join(' · '),weightText=ranked.map(x=>`${esc(x.stat)} ${Number(x.value||0).toFixed(4)}${x.first_effective_delta==null?'':` @ +${Number(x.first_effective_delta)}`}`).join(' · '),delta=g.delta_seconds_per_mob,fpRows=Array.isArray(fp.iterations)?fp.iterations:[],fpText=fpRows.length?`<div class="muted">fixed-point trace · ${fpRows.map(x=>`I${Number(x.index)} ${Number(x.seconds_per_mob).toFixed(2)}s · ${x.gear_candidate_id==='none'?'naked':'gear'} · ${esc((x.policy_candidate_id||'policy').split('|')[0])}`).join(' → ')} · ${esc(fp.stop_reason||'—')}</div>`:'';return `<div class="coverage-box small"><b>Generic Gear + Stat Sensitivity</b><div style="margin-top:4px">${Number(g.item_count||items.length)} named items · SP ${Number(a.spell_power||0)} · Int ${Number(a.intellect||0)} · Spi ${Number(a.spirit||0)} · MP5 ${Number(a.mp5||0)}</div><div class="muted">${esc(g.selection_method||'gear selection')} · fixed point ${g.fixed_point_complete===true?'complete':'not complete'}${fp.iteration_count?` · ${Number(fp.iteration_count)} states`:''}${g.naked_seconds_per_mob==null?'':` · ${Number(g.naked_seconds_per_mob).toFixed(2)}s → ${Number(g.geared_seconds_per_mob).toFixed(2)}s/mob${delta==null?'':` · ${Number(delta).toFixed(2)}s`}`}</div>${fpText}${weightText?`<div class="muted">exact scorer sensitivity · ${weightText}</div>`:''}${itemNames?`<div class="muted">${itemNames}${items.length>8?' · …':''}</div>`:''}</div>`}
function genericPolicyCondition(c){const k=String(c?.kind||'condition');if(k==='aura_present'||k==='aura_missing')return `${esc(c.scope||'target')} aura ${k==='aura_present'?'present':'missing'} · ${esc(c.aura_id||'—')}`;if(k==='resource_threshold')return `${esc(c.resource_id||'resource')} ${esc(c.operator||'gte')} ${c.threshold_source==='action_cost'?'action cost':esc(c.value??'—')}`;if(k==='target_state')return `target ${esc(c.field||'state')} ${esc(c.operator||'eq')} ${esc(c.value)}`;return esc(k)}
function genericPolicySummary(r){const p=r?.policy||{},rules=Array.isArray(p.rules)?p.rules:[],maint=Array.isArray(p.maintenance)?p.maintenance:[];if(!rules.length&&!maint.length)return '';const ruleText=rules.map(x=>`${esc(x.id||'rule')} → ${esc(x.action_id||'—')} [${(Array.isArray(x.conditions)?x.conditions:[]).map(genericPolicyCondition).join(' + ')}]`).join('<br>'),maintText=maint.map(x=>`${esc(x.name||x.family_key||'maintenance')} (${esc(x.execution_status||'declared')})`).join(' · '),prov=p.provenance||{},searched=prov.search_performed===true,eff=prov.search_efficiency||{},effText=Number.isFinite(Number(eff.expensive_evaluations))?` · simulations ${esc(eff.expensive_evaluations)}/${esc(eff.requests)} · avoided ${esc(eff.expensive_evaluations_avoided)} (${esc(eff.dominance_pruned_requests)} dominance-pruned, ${esc(eff.cache_hits)} cache hits)`:'' ,searchText=searched?`bounded search · ${esc(prov.candidate_count??'—')} candidates · ${esc(prov.valid_candidate_count??'—')} valid · improved ${Number(prov.improvement_vs_seed_seconds_per_mob||0).toFixed(3)}s/mob vs seed${effText}`:prov.search_performed===false?'no search yet':'';return `<div class="coverage-box small"><b>Canonical Policy IR</b><div style="margin-top:4px">${esc(p.label||p.id||p.kind||'priority policy')}</div>${maint.length?`<div class="muted">maintenance · ${maintText}</div>`:''}${rules.length?`<div class="muted">combat priority<br>${ruleText}</div>`:''}<div class="muted">${prov.authority==='canonical_game_ir'?'runtime authority · Game IR':prov.authority==='generic_policy_threshold_search'?'runtime authority · threshold-searched Game IR policy':prov.authority==='generic_policy_search'?'runtime authority · searched Game IR policy':'policy publication'}${searchText?` · ${searchText}`:''}</div></div>`}

function genericEvaluationSummary(r){const ev=r?.provenance?.evaluation;if(!ev)return '';const d=ev.diagnostics||{},rm=ev.resource_metrics||{},dmg=d.damage||{},tc=d.timing_consistency||{},rec=d.recovery||{},mana0=rm?.before?.mana,mana1=rm?.after?.mana,postMana=rm?.post_recovery?.after?.mana,scope=ev.evaluation_scope||'evaluation',ready=ev.optimization_ready===true?'optimization ready':'not optimization-ready',kill=Number(ev.kill_seconds_per_mob??0),recovery=ev.recovery_seconds_per_mob==null?null:Number(ev.recovery_seconds_per_mob),cycle=Number(ev.seconds_per_mob??kill);return `<div class="coverage-box small"><b>Canonical Evaluation</b><div style="margin-top:4px">kill ${kill.toFixed(2)}s${recovery==null?'':` · recovery ${recovery.toFixed(2)}s · combat+recovery ${cycle.toFixed(2)}s`} · target ${Number(d.target_start_health||0).toFixed(0)} HP · ${Number(d.action_count||0)} actions · damage ${Number(dmg.total||0).toFixed(2)} (${Number(dmg.direct||0).toFixed(2)} direct + ${Number(dmg.periodic||0).toFixed(2)} periodic)</div><div class="muted">${esc(scope)} · ${esc(ready)}${mana0==null?'':` · Mana ${Number(mana0).toFixed(0)}→${Number(mana1).toFixed(0)}${postMana==null?'':`→${Number(postMana).toFixed(0)} recovered`}`} · event timing ${tc.consistent===true?'consistent':'incomplete'} · provenance ${esc(ev.provenance?.producer||'canonical')}</div>${recovery==null?'':`<div class="muted">recovery · ${esc(rec.method||'stateful')} · HP missing ${Number(rec.health_missing_before||0).toFixed(0)} · Mana missing ${Number(rec.mana_missing_before||0).toFixed(0)} · ${esc(rec.water_tier||'ordinary water')}${Number(rec.heal_casts||0)>0?` · ${Number(rec.heal_casts)}× ${esc(rec.heal_action_id||'heal')}`:''}</div>`}</div>`}

function renderBackendComparison(){const rows=(data?.comparisons||[]).filter(x=>String(x?.class_name||'').toLowerCase()===String(state.cls||'').toLowerCase()&&Number(x?.level)===Number(state.level));const c=rows[0];if(!c)return '';const sum=c.summary||{},cats=c.categories||{},resolved=c.resolved_generic_mismatches||[];const cards=Object.entries(cats).map(([name,row])=>{const cls=(row?.classification||[]).map(esc).join(' · '),delta=row?.delta?.seconds_per_mob??row?.delta?.kill_seconds_per_mob;return `<div class="cmp-card"><b>${esc(name.replaceAll('_',' '))}</b> ${badge(row?.status||'—',row?.status==='parity'?'good':row?.status==='explicit'?'warn':'')}<div class="small" style="margin-top:5px">${delta==null?'':`Δ ${Number(delta).toFixed(3)}s · `}${cls||'classified'}</div></div>`}).join('');return `<div class="cmp"><div class="cmp-card"><b>Legacy Balance</b><div class="kpi">${sec(sum.legacy_seconds_per_mob)}</div><div class="small muted">kill ${sec(sum.legacy_kill_seconds_per_mob)} · recovery ${sec(sum.legacy_recovery_seconds_per_mob)} · travel ${sec(sum.legacy_travel_seconds_per_mob)}</div></div><div class="cmp-card"><b>Generic caster</b><div class="kpi">${sec(sum.generic_seconds_per_mob)}</div><div class="small muted">kill ${sec(sum.generic_kill_seconds_per_mob)} · recovery ${sec(sum.generic_recovery_seconds_per_mob)} · travel ${sec(sum.generic_travel_seconds_per_mob)}</div></div><div class="cmp-card"><b>Classified delta</b><div class="kpi">${sum.seconds_per_mob_delta==null?'—':(Number(sum.seconds_per_mob_delta)>=0?'+':'')+Number(sum.seconds_per_mob_delta).toFixed(2)+'s'}</div><div class="small muted">${esc(c.status||'—')} · unexplained ${(c.unexplained_categories||[]).length}</div></div></div><div class="cmp" style="margin-top:8px">${cards}</div>${resolved.length?`<div class="coverage-box small"><b>Resolved generic mismatch</b><div class="good" style="margin-top:4px">${resolved.map(x=>esc(x.id||'resolved')).join(' · ')}</div></div>`:''}<div class="small muted" style="margin-top:7px">Comparison is oracle-only: legacy values do not feed generic execution.</div>`}
function genericAvailabilitySummary(cls){
  if(String(data?.active_backend)!=='generic')return '';
  const m=classMeta(cls),bounds=m.source_ir_level_bounds||{},race=m.race_availability||{},levels=m.planning_levels||[];
  const source=bounds.min!=null?`source IR L${esc(bounds.min)}–L${esc(bounds.max)}`:'source IR unverified';
  const plan=levels.length?`native route L${esc(levels[0])}–L${esc(levels.at(-1))}`:'no verified native route';
  const availability=m.selected_level_source_ir_available?'IR level in range':'IR level outside declared range';
  const scenario=race.representative_scenario_race?` · scenario race ${esc(race.representative_scenario_race)}`:'';
  return `<div class="coverage-box small"><b>Generic class support · ${esc(classLabel(cls))}</b><div style="margin-top:4px">${source} · ${plan} · ${esc(availability)}${scenario}</div><div class="muted">Playable race selection: not verified. Source IR, executable route corridor and complete leveling fidelity are separate capabilities.</div></div>`;
}
function genericPublicationCoverage(r){
  if(String(data?.active_backend)!=='generic')return '';
  const coverage=r?.capability?.publication_sections||{},sections=coverage.sections||{};
  const keys=['selected_build','gear','stat_weights','policy','timing','route','fidelity_provenance'];
  if(!keys.every(k=>sections[k]?.status))return '';
  const labels={selected_build:'Build',gear:'Gear',stat_weights:'Stat weights',policy:'Policy',timing:'Timing',route:'Route',fidelity_provenance:'Fidelity/source'};
  const manifest=r?.publication_availability||{},fields=['selected_build','gear','stat_weights','policy','timing','route'];
  const fieldLine=fields.every(k=>manifest[k])?`<div class="muted">Level-record fields: ${fields.map(k=>`${esc(labels[k])} ${esc(manifest[k])}`).join(' · ')}. Native route steps are separate.</div>`:'';
  return `<div class="coverage-box small"><b>Generic publication coverage · DecisionRecord L${esc(r?.identity?.level??'—')}${Number(state.level)!==Number(r?.identity?.level)?` · route focus L${esc(state.level)} (separate native route rows)`:''}</b><div style="margin-top:5px">${keys.map(k=>{const x=sections[k],ok=x.status==='available',style=ok?'good':x.status==='partial'?'warn':'muted';return `<span class="pill ${style}" title="${esc(x.reason||'')}">${esc(labels[k])}: ${esc(x.status)}</span>`}).join('')}</div><div class="muted">${keys.filter(k=>sections[k].status!=='available').map(k=>`${esc(labels[k])}: ${esc(sections[k].reason)}`).join('<br>')}</div>${fieldLine}</div>`;
}
// G48c: a native route-scored Lxx decision is *not* the source-only
// DecisionRecord at the API's selected level. Both remain visible separately.
function nativeRouteDecisionForFocus(){
  if(String(data?.active_backend)!=='generic'||!state.route)return null;
  return (data?.native_route_decisions||[]).find(r=>
    String(r?.identity?.class_name)===String(state.cls)&&
    String(r?.identity?.route)===String(state.route)&&
    Number(r?.identity?.target_level)===Number(state.target)&&
    Number(r?.identity?.level)===Number(state.level))||null;
}
function genericNativeRouteDecisionSummary(){
  if(String(data?.active_backend)!=='generic')return '';
  const r=nativeRouteDecisionForFocus();
  if(!r)return '';
  const id=r.identity||{},o=r.objective||{},t=r.timing||{},gear=r.gear||{},tal=r.talents||{},p=r.policy||{},f=r.fidelity||{},w=r.stat_weights||{};
  const proxy=gear.status==='scenario_proxy_no_named_items';
  const stats=w.stats||{},ranked=Object.entries(stats).sort((a,b)=>Number(b[1]?.seconds_saved_per_100_per_point||0)-Number(a[1]?.seconds_saved_per_100_per_point||0));
  const weightText=ranked.length?ranked.map(([name,x])=>`${esc(name)} ${Number(x.seconds_saved_per_100_per_point).toFixed(3)}s/100/pt`).join(' · '):'not measured';
  const timingText=`${t.seconds_per_mob==null?'—':Number(t.seconds_per_mob).toFixed(3)+'s/mob'}${t.kill_seconds_per_mob==null?'':' · kill '+Number(t.kill_seconds_per_mob).toFixed(3)+'s'}${t.recovery_seconds_per_mob==null?'':' · recovery '+Number(t.recovery_seconds_per_mob).toFixed(3)+'s'}${t.travel_seconds_per_mob==null?' · travel unmodeled':' · travel '+Number(t.travel_seconds_per_mob).toFixed(3)+'s'}`;
  const namedCount=Object.keys(gear.slots||{}).length;
  const warning=(f.quality_warnings||[]).map(esc).join(' · ');
  return `<div class="coverage-box small" id="nativeRouteDecision"><b>Native route-scored DecisionRecord · ${esc(id.class_name)} L${esc(id.level)} / target L${esc(id.target_level)} · ${esc(id.route)}</b><div style="margin-top:5px">${badge('NATIVE ROUTE SCORE','good')} <b>${mph(o.mobs_per_hour)}</b> · ${esc(timingText)}</div><div class="rowline"><b>Talent build</b> · <code>${esc(tal.allocation||'—')}</code> · ${esc(tal.family||'—')}</div><div class="rowline"><b>Policy</b> · ${esc(p.label||'—')}</div><div class="rowline"><b>Gear provenance</b> · ${esc(gear.selection_method||'unknown')} · ${proxy?'scenario proxy; no named gear':`${namedCount} named catalogue slots`}</div><div class="rowline"><b>${proxy?'Proxy stat sensitivities':'Exact-state stat weights'}</b> · ${weightText}</div><div class="muted">Canonical ${esc(r.provenance?.route_authority||'native')} · bounded corridor; no full-leveling or cross-class score comparability. ${t.complete===true?'Timing complete.':'Timing incomplete.'} Source-only selected-level DecisionRecord shown separately below.</div>${warning?`<div class="warn">Limits: ${warning}</div>`:''}</div>`;
}
async function enqueueNativeQueueDecision(){
 const cls=String(state.cls),level=Number(state.level),levels=classMeta(cls).queued_native_decision_levels||[];
 if(nativeQueueSubmitting||!levels.includes(level))return;
 nativeQueueSubmitting=true;queuedNativeView=null;renderQueuedNativeView();
 const body={ruleset:'forever',class_name:cls,start_level:level,end_level:level,
  objective:'endpoint',endpoint_mode:'generic_decision',forever_build_as_of:NATIVE_QUEUE_AS_OF,
  source_snapshot:'current',engine_semantic_hash:'current',policy_space_version:'current',
  config:{},validation_modes:[],priority:0,deduplicate:false};
 try{
  const resp=await fetch('/api/service/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const payload=await resp.json();
  if(!resp.ok)throw new Error('HTTP '+resp.status+' · '+String(payload.error||'rejected'));
  const job=payload.job;
  if(payload.created!==true||!nativeQueueRequestMatches(job,cls,level))throw new Error('queue admission identity mismatch');
  nativeQueueJob={id:job.id,cls,level,state:job.state||'queued',failures:0,error:''};
  saveNativeQueueJob();
  void pollNativeQueueStatus();
 }catch(e){
  // Never guess whether a timed-out POST was accepted. No implicit retry/requeue.
  nativeQueueJob={id:'',cls,level,state:'submission_unknown',failures:0,error:String(e)};
  saveNativeQueueJob();
 }finally{nativeQueueSubmitting=false;renderQueuedNativeView()}
}
async function pollNativeQueueStatus(force=false){
 const tracked=nativeQueueJob;
 if(!tracked?.id||nativeQueuePolling)return;
 if(!force&&(['completed','failed','cancelled','connection_lost'].includes(tracked.state)))return;
 nativeQueuePolling=true;
 try{
  const resp=await fetch(`/api/service/jobs/${encodeURIComponent(tracked.id)}`,{cache:'no-store'});
  const job=await resp.json();
  if(!resp.ok)throw new Error('HTTP '+resp.status+' · '+String(job.error||'unavailable'));
  if(!nativeQueueRequestMatches(job,tracked.cls,tracked.level)||job.id!==tracked.id)
   throw new Error('job identity/producer mismatch');
  if(!['queued','running','paused','completed','failed','cancelled'].includes(job.state))
   throw new Error('unexpected job state');
  if(nativeQueueJob!==tracked)return;
  tracked.state=job.state;tracked.failures=0;
  tracked.error=job.state==='failed'?String(job.error||job.runtime_message||'worker failed'):
   job.state==='cancelled'?'job cancelled':'';
 }catch(e){
  if(nativeQueueJob!==tracked)return;
  tracked.failures++;
  tracked.error=String(e);
  tracked.state=tracked.failures>=3?'connection_lost':'checking';
 }finally{nativeQueuePolling=false;if(nativeQueueJob===tracked)renderQueuedNativeView()}
}
function renderQueuedNativeView(){
 const box=$('queuedNativeResult'),button=$('loadQueuedNative');if(!box||!button)return;
 const levels=classMeta(state.cls)?.queued_native_decision_levels||[];
 const allowed=levels.includes(Number(state.level));
 const tracked=nativeQueueMatchesSelection()?nativeQueueJob:null;
 const queueButton=$('enqueueQueuedNative'),retry=$('retryQueuedNative'),status=$('queuedNativeStatus');
 const active=tracked&&['checking','queued','running','paused'].includes(tracked.state);
 queueButton.disabled=!allowed||nativeQueueSubmitting||!!active;
 retry.style.display=tracked?.state==='connection_lost'?'inline-block':'none';
 button.disabled=!allowed||!!(tracked&&tracked.state!=='completed');
 if(status){status.textContent=!allowed?'Native queue unavailable for this class/level.':
  tracked?`Job ${tracked.id.slice(0,10)} · ${tracked.state}${tracked.error?' · '+tracked.error:''}${tracked.state==='completed'?' · click Inspect to verify current publication':''}`:
  nativeQueueJob?`Tracking ${nativeQueueJob.cls} L${nativeQueueJob.level} in this tab; select that level to inspect.`:
  'No job tracked. Queue a native source Decision or inspect the current committed publication.'}
 if(!allowed){box.textContent='No provider-declared native queued Decision for this class/level.';return}
 if(tracked&&tracked.state!=='completed'){box.textContent='Queued result is not inspectable until the tracked job completes.';return}
 const view=queuedNativeView;
 if(!view||view.class_name!==state.cls||view.level!==Number(state.level)){
  box.textContent='No queued result inspected. Click to read current native publication.';return
 }
 if(view.error){box.textContent='Queued result unavailable: '+view.error;return}
 const p=view.payload||{},r=p.decision||{},id=r.identity||{},b=r.backend||{},obj=r.objective||{};
 box.innerHTML=`<b>Immutable queue artifact · ${esc(p.publication_id||'—')}</b><div>class ${esc(id.class_name||'—')} · L${esc(id.level??'—')} · backend ${esc(b.id||'—')}@${esc(b.version||'—')}</div><div>authority ${esc(p.execution_authority||'—')} · source ${esc(r.provenance?.source||'—')} · legacy fallback disabled</div><div>objective ${esc(obj.status||'—')} · mobs/h ${obj.mobs_per_hour==null?'not proven':esc(obj.mobs_per_hour)}</div><div class="muted">Source-only queued Decision; not a full optimized leveling route. Regular Decisions publication is unchanged.</div>`;
}
async function loadQueuedNativeDecision(){
 const cls=String(state.cls),level=Number(state.level),seq=++queuedNativeSequence;
 queuedNativeView={class_name:cls,level,error:'loading'};renderQueuedNativeView();
 try{
  const resp=await fetch(`/api/decisions/queued?backend=generic&class=${encodeURIComponent(cls)}&level=${encodeURIComponent(level)}`,{cache:'no-store'});
  const payload=await resp.json();
  if(!resp.ok)throw new Error('HTTP '+resp.status+' · '+String(payload.error||'unavailable'));
  const r=payload.decision||{},id=r.identity||{};
  if(nativeQueueMatchesSelection()&&nativeQueueJob.state==='completed'&&payload.job_id!==nativeQueueJob.id)
    throw new Error('current publication belongs to another job; this job cannot be inspected as current');
  if(payload.authority!=='queued_native_generic_decision'||payload.legacy_fallback!==false||
     payload.execution_authority!=='native_generic_decision'||r.backend?.id!=='generic'||
     id.class_name!==cls||Number(id.level)!==level||r.provenance?.legacy_fallback!==false)
    throw new Error('queue publication identity/authority mismatch');
  if(seq!==queuedNativeSequence||state.cls!==cls||Number(state.level)!==level)return;
  queuedNativeView={class_name:cls,level,payload};renderQueuedNativeView();
 }catch(e){if(seq!==queuedNativeSequence||state.cls!==cls||Number(state.level)!==level)return;
  queuedNativeView={class_name:cls,level,error:String(e)};renderQueuedNativeView()}
}
function renderBackendPublication(){const box=$('backendPublication'),meta=$('backendPublicationMeta'),records=(data?.decisions||[]).filter(r=>String(r?.identity?.class_name)===String(state.cls)),backend=(data?.backends||[]).find(x=>String(x.id)===String(data?.active_backend||state.backend))||{};if(meta){const selection=data?.backend_selection||{},selectionLabel=backendExplicit?'explicit':'auto · '+String(selection.reason||'capability-gated');meta.textContent=`${backend.id||state.backend}${backend.version?'@'+backend.version:''} · ${selectionLabel} · ${records.length} record${records.length===1?'':'s'} for ${classLabel(state.cls)}`;}if(!box)return;const comparisonHtml=renderBackendComparison();if(comparisonHtml){box.innerHTML=comparisonHtml;return}const r=records.find(x=>Number(x?.identity?.level)===Number(state.level))||records[0];if(!r){box.innerHTML='<div class="focus-empty">Selected backend published no record for this class.</div>';return}const cap=r.capability||{},unsupported=r.unsupported_mechanics||[],obj=r.objective||{},actors=r.actors||[],resources=r.resources||[],actions=r.actions||[],counts=`actors ${actors.length} · resources ${resources.length} · actions ${actions.length} · modes ${(r.modes||[]).length}`,score=obj.mobs_per_hour==null?(String(obj.status||'').startsWith('combat_')?`${Number(r?.timing?.kill_seconds_per_mob||0).toFixed(2)}s kill${r?.timing?.recovery_seconds_per_mob==null?'':` + ${Number(r.timing.recovery_seconds_per_mob).toFixed(2)}s recovery`}`:obj.status==='runtime_probe'?'runtime probe':'objective unavailable'):mph(obj.mobs_per_hour),talentHtml=genericTalentSummary(r),frontierHtml=genericFrontierSummary(r),routeHtml=genericRouteSummary(r),gearStatHtml=genericGearStatSummary(r),modeHtml=genericModeSummary(r),autoAttackHtml=genericAutoAttackSummary(r),energyHtml=genericEnergySummary(r),comboPointHtml=genericComboPointSummary(r),eventResourceHtml=genericEventResourceSummary(r),incomingDamageHtml=genericIncomingDamageSummary(r),eventTriggerHtml=genericEventTriggerSummary(r),multiActorHtml=genericMultiActorSummary(r),timedSummonHtml=genericTimedSummonSummary(r),hunterPetHtml=genericHunterPetSummary(r),warriorHtml=genericWarriorSummary(r),rogueHtml=genericRogueSummary(r),priestHtml=genericPriestSummary(r),shamanHtml=genericShamanSummary(r),modeActionPolicyHtml=genericModeActionPolicySummary(r),crossModePolicyHtml=genericCrossModePolicySummary(r),policyHtml=genericPolicySummary(r),evaluationHtml=genericEvaluationSummary(r),runtimeHtml=genericRuntimeSummary(r),periodicHtml=genericPeriodicRuntimeSummary(r),healingHtml=genericHealingRuntimeSummary(r),stateHtml=(actors.some(a=>a?.state_status==='source_backed_starting_state')||resources.some(x=>['source_backed_starting_state','qualified_proxy_starting_state','mode_managed_resource_definition','event_driven_resource_definition'].includes(x?.state_status)))?`<div class="coverage-box small"><b>IR starting state</b><div style="margin-top:4px">${actors.filter(a=>a?.state_status==='source_backed_starting_state').map(genericActorStateSummary).join('<br>')}${resources.filter(x=>['source_backed_starting_state','qualified_proxy_starting_state','mode_managed_resource_definition','event_driven_resource_definition'].includes(x?.state_status)).map(genericResourceStateSummary).join('<br>')}</div></div>`:'',actionHtml=actions.length?`<div class="coverage-box small"><b>Source-backed Game IR</b><div style="margin-top:4px">${actions.slice(0,6).map(genericActionSummary).join('<br>')}</div></div>`:'',ir=r.provenance?.game_ir||{},overlays=ir.overlays||[],semanticGaps=ir.unsupported_semantics||[],overlayHtml=(overlays.length||semanticGaps.length)?`<div class="coverage-box small"><b>IR provenance &amp; overlays</b><div class="muted" style="margin-top:4px">${overlays.length?`${overlays.length} dated field overlay${overlays.length===1?'':'s'} · ${overlays.map(x=>`${esc(x.operation||'overlay')} ${Number(x.value??0)} @ ${esc(x.effective_from||'—')}`).join(' · ')}`:'no active overlay'}${semanticGaps.length?`<br>${semanticGaps.length} explicit semantic caveat${semanticGaps.length===1?'':'s'} · ${semanticGaps.map(x=>esc(x.code||x.status||'unsupported')).join(' · ')}`:''}</div></div>`:'';box.innerHTML=`${genericAvailabilitySummary(state.cls)}${genericNativeRouteDecisionSummary()}${genericPublicationCoverage(r)}<div class="cmp"><div class="cmp-card"><b>${esc(r.backend?.id||'backend')} · ${esc(r.identity?.class_name||'')}</b><div class="kpi">${esc(score)}</div><div class="small muted">L${esc(r.identity?.level??'—')} · ${esc(r.identity?.route||'—')} · ${esc(cap.status||r.fidelity?.rating||'available')}</div></div><div class="cmp-card"><b>Decision contract</b><div class="small">${esc(counts)}</div><div class="small muted">producer ${esc(r.provenance?.producer||r.backend?.implementation||'—')} · legacy fallback ${r.provenance?.legacy_fallback===false?'disabled':'not declared'}</div></div></div>${genericPlayableDruidStepSummary()}${talentHtml}${frontierHtml}${routeHtml}${gearStatHtml}${modeHtml}${autoAttackHtml}${energyHtml}${comboPointHtml}${eventResourceHtml}${incomingDamageHtml}${eventTriggerHtml}${multiActorHtml}${timedSummonHtml}${hunterPetHtml}${warriorHtml}${rogueHtml}${priestHtml}${shamanHtml}${modeActionPolicyHtml}${crossModePolicyHtml}${policyHtml}${evaluationHtml}${runtimeHtml}${periodicHtml}${healingHtml}${stateHtml}${actionHtml}${overlayHtml}${unsupported.length?`<div class="coverage-box small"><b>Explicitly unsupported</b><div class="muted" style="margin-top:4px">${unsupported.map(x=>esc(x)).join(' · ')}</div></div>`:''}`}

function syncProductSurface(){const enabled=data?.product_surface?.route_navigation!==false&&(data?.active_backend!=='generic'||targetsFor(state.cls).length>0);document.querySelectorAll('.route-product').forEach(el=>{el.style.display=enabled?'':'none'});const note=data?.product_surface?.note||'';$('authority').textContent=note||data?.authority_note||''}
function renderAll(){renderQueuedNativeView();syncProductSurface();renderBackendPublication();if(data?.product_surface?.route_navigation!==false&&(data?.active_backend!=='generic'||targetsFor(state.cls).length>0)){syncClassSpecificControls();renderClassCompare();renderSpecCompare();renderReferenceCompare();renderFocus();renderRoute();renderDual();renderDiagnostics();refreshWowheadLinks()}else{$('focusBadges').innerHTML='';document.getElementById('nativeRouteScope')?.remove()}}
// G46e: bound an expensive cold Decision load and keep the last good publication
// visible. Explicit retry instead of an infinite spinner or unhandled rejection.
let decisionLoadSequence=0;
// G49b: a successful HTTP response is not authority if it contradicts the
// service's declared backend choice. Reject mismatched/misrouted payloads
// instead of silently rendering legacy when generic was explicitly or
// automatically selected. No fallback or speculative retry is permitted.
// G49c: a backend match alone is not enough. The selected class and level
// must be the ones actually requested; an otherwise valid stale/misrouted
// response must never replace the current Decision publication.
function assertDecisionBackendSelection(payload,explicit,requestedBackend,requestedClass,requestedLevel){
 const active=String(payload?.active_backend||''),selection=payload?.backend_selection||{};
 const eligible=selection.generic_default_eligible;
 if(!['legacy','generic','compare'].includes(active)||
    selection.backend!==active||selection.legacy_fallback!==false||
    selection.mode!==(explicit?'explicit':'automatic')||
    selection.class_name!==requestedClass||selection.level!==requestedLevel||
    payload?.selected_level!==requestedLevel||
    typeof eligible!=='boolean'||
    (explicit&&active!==requestedBackend)||
    (!explicit&&((active==='generic')!==eligible))){
   throw new Error('backend selection authority mismatch (request identity); refusing to publish response');
 }
}

async function reloadDecisions(options={}){
 const seq=++decisionLoadSequence, previous=data, controller=new AbortController();
 const requestedClass=String(state.cls),requestedLevel=Number(state.level),
       requestedBackend=String(state.backend),explicit=backendExplicit;
 // G48d: an explicit source-only level change can require a cold seven-class
 // publication (~38s measured for L20). Keep the normal 20s G46e guard; only
 // this deliberate level request gets a finite 60s allowance.
 const timeoutMs=options.sourceOnlyLevelChange===true||!explicit?60000:20000;
 const cutoff=setTimeout(()=>controller.abort(),timeoutMs);
 const panel=$('backendPublication'), meta=$('backendPublicationMeta');
 if(meta)meta.textContent=options.sourceOnlyLevelChange===true?
   'Loading source-only level… (up to 60 seconds; previous data preserved on failure)':
   'Loading decisions… (cold generic evaluations may be slow)';
 try{
  const level=Number.isFinite(requestedLevel)?`&level=${encodeURIComponent(requestedLevel)}`:'';
  // Every request carries its class and level, including explicit overrides.
  // Only omission of the backend parameter requests capability-aware Auto.
  const cls=`class=${encodeURIComponent(requestedClass)}`;
  const endpoint=explicit?
    `/api/decisions?backend=${encodeURIComponent(requestedBackend)}&${cls}${level}`:
    `/api/decisions?${cls}${level}`;
  const r=await fetch(endpoint,{cache:'no-store',signal:controller.signal});
  if(!r.ok)throw new Error(`decisions HTTP ${r.status}`);
  const next=await r.json();
  // A local class/level change in explicit mode need not issue another HTTP
  // request, so sequence alone cannot detect every stale in-flight response.
  if(seq!==decisionLoadSequence||state.cls!==requestedClass||
     Number(state.level)!==requestedLevel||backendExplicit!==explicit||
     (explicit&&state.backend!==requestedBackend))return;
  assertDecisionBackendSelection(next,explicit,requestedBackend,requestedClass,requestedLevel);
  data=next;state.backend=String(data?.active_backend||state.backend);
  syncState();$('jobEnd').value=state.target;renderAll();syncIntentControls();
 }catch(e){
  if(seq!==decisionLoadSequence)return;
  data=previous;
  // A failed source-only level request must not leave the level picker claiming
  // L20 while the still-visible source DecisionRecord is actually from L10.
  if(data?.active_backend==='generic'&&!targetsFor(state.cls).length){
    state.level=Number(data?.selected_level??20);
    syncState();
  }
  const reason=e?.name==='AbortError'?`Request exceeded ${timeoutMs/1000} seconds`:String(e);
  if(meta)meta.textContent='Decision loading failed · previous publication retained';
  if(panel)panel.innerHTML=`<div class="coverage-box"><b>Decision loading failed</b><div class="small muted">${esc(reason)}. No new decision was published.</div><button type="button" id="retryDecisionLoad">Retry decisions</button></div>`;
  $('retryDecisionLoad')?.addEventListener('click',()=>{void reloadDecisions()});
 }finally{clearTimeout(cutoff)}
}
function scrollToLevel(){const el=$(`route-L${Number(state.level)}`);if(el)el.scrollIntoView({behavior:'smooth',block:'center'})}
function bind(){ $('loadQueuedNative').addEventListener('click',loadQueuedNativeDecision);$('enqueueQueuedNative').addEventListener('click',enqueueNativeQueueDecision);$('retryQueuedNative').addEventListener('click',()=>{if(nativeQueueJob){nativeQueueJob.failures=0;nativeQueueJob.state='checking';renderQueuedNativeView();void pollNativeQueueStatus(true)}}); $('backendPick').addEventListener('change',async e=>{const choice=e.target.value;backendExplicit=choice!=='auto';localStorage.setItem('foreverDecisionBackendExplicit',backendExplicit?'1':'0');if(backendExplicit)state.backend=choice;await reloadDecisions()}); $('focusBoard').addEventListener('click',e=>{const b=e.target.closest('button[data-focus-action]');if(!b)return;if(b.dataset.focusAction==='continuation'){$('currentTalents').scrollIntoView({behavior:'smooth',block:'center'});$('currentTalents').focus();return}if(b.dataset.focusAction==='compare'){const u=$('focusCompareBuildUrl');if(u){$('compareBuildUrl').value=u.value;localStorage.setItem('foreverCompareBuildUrl',u.value)}runBuildComparison()}}); $('compareBuildUrl').value=localStorage.getItem('foreverCompareBuildUrl')||'';$('compareBuildMode').value=localStorage.getItem('foreverCompareBuildMode')||'same_gear';$('compareBuildRun').addEventListener('click',runBuildComparison);$('compareBuildMode').addEventListener('change',e=>localStorage.setItem('foreverCompareBuildMode',e.target.value));$('compareBuildUrl').addEventListener('keydown',e=>{if(e.key==='Enter')runBuildComparison()});$('referenceCompare').addEventListener('click',e=>{const b=e.target.closest('button[data-ref-compare-url]');if(!b)return;$('compareBuildUrl').value=b.dataset.refCompareUrl||'';runBuildComparison()}); $('classPick').addEventListener('change',e=>{state.cls=e.target.value;state.target='';state.route='';state.level=NaN;syncState({allowEmptyClass:true});$('jobEnd').value=state.target;renderAll();if(!backendExplicit){void reloadDecisions()}loadServiceStatus()});$('targetPick').addEventListener('change',e=>{state.target=e.target.value;state.route='';state.level=NaN;syncState();$('jobEnd').value=state.target;renderAll()});$('routePick').addEventListener('change',e=>{state.route=e.target.value;state.level=NaN;syncState();renderAll()});$('levelPick').addEventListener('change',e=>{state.level=Number(e.target.value);if(data?.active_backend==='generic'&&!targetsFor(state.cls).length){void reloadDecisions({sourceOnlyLevelChange:true});return}syncState();renderAll()});$('referencePick').addEventListener('change',()=>renderReferenceCompare());$('currentLevel').addEventListener('change',e=>{const v=Number(e.target.value);const ts=targetsFor(state.cls).filter(x=>x>=v);setOptions($('continueTarget'),ts.map(x=>({value:x,label:`target L${x}`})),ts.includes(Number(state.target))?state.target:ts.at(-1))});$('continueRun').addEventListener('click',runContinuation);$('validateIceLance').addEventListener('click',runIceLanceValidation);$('enqueueJob').addEventListener('click',enqueueSelectedJob);$('addItemButton').addEventListener('click',addSelectedItem);$('refreshItemsButton').addEventListener('click',refreshAllItems);$('refreshAbilitiesButton').addEventListener('click',()=>refreshAbilityData('index'));$('fetchAbilityDetailsButton').addEventListener('click',()=>refreshAbilityData('details'));$('addItemInput').addEventListener('keydown',e=>{if(e.key==='Enter')addSelectedItem()});$('jobAction').addEventListener('change',syncIntentControls);$('jobStart').addEventListener('change',()=>{if($('jobAction').value!=='recompute_range')$('jobEnd').value=$('jobStart').value});$('clearClone').addEventListener('click',()=>setCloneSource(null));$('refreshJobs').addEventListener('click',()=>{loadServiceStatus();loadRuntimeStatus()});$('stopWorkers').addEventListener('click',()=>runtimeCommand('stop-daemon'));$('stopAll').addEventListener('click',()=>runtimeCommand('stop-all'));$('jobList').addEventListener('click',e=>{const t=e.target.closest('button[data-history-toggle]');if(t){processingHistoryExpanded=!processingHistoryExpanded;loadServiceStatus();return}const b=e.target.closest('button[data-job-action]');if(!b)return;if(b.dataset.jobAction==='hide_local'){hiddenProcessingJobs.add(b.dataset.jobId);persistHiddenProcessingJobs();loadServiceStatus();return}controlJob(b.dataset.jobId,b.dataset.jobAction)});$('publicationList').addEventListener('click',e=>{const t=e.target.closest('button[data-publication-history-toggle]');if(!t)return;legacyPublicationsExpanded=!legacyPublicationsExpanded;renderPublications(lastServiceSnapshot||{publications:[]})});$('savedStatePanel').addEventListener('click',e=>{const b=e.target.closest('button[data-saved-mode]');if(b)selectSavedState(b.dataset.jobId,b.dataset.checkpointId,b.dataset.savedMode)})}
let runtimeToken='';
async function loadRuntimeStatus(){const box=$('runtimeControls');try{const r=await fetch('/api/runtime',{cache:'no-store'}),j=await r.json();runtimeToken=j.token||'';if(box)box.style.display=(j.managed&&j.available)?'inline-flex':'none';const sw=$('stopWorkers');if(sw)sw.disabled=!(j.children?.daemon?.running)}catch(e){runtimeToken='';if(box)box.style.display='none'}}
async function runtimeCommand(command){const msg=$('serviceMessage');if(!runtimeToken){msg.textContent='Rejected: local stack controls unavailable';return}const label=command==='stop-all'?'stop all':'stop optimizer';if(command==='stop-all'&&!window.confirm('Stop listener, optimizer workers and service API?'))return;msg.textContent=`Pending: ${label}…`;try{const r=await fetch('/api/runtime/command',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Stack-Token':runtimeToken},body:JSON.stringify({command})}),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);msg.textContent=`Accepted: ${label}`;if(command==='stop-daemon')setTimeout(()=>{loadRuntimeStatus();loadServiceStatus()},500)}catch(e){msg.textContent='Rejected: '+e}}
function jobIntent(j){const r=j.request||{},m=(r.config||{}).service_intent||{};const action=m.action||'recompute_range',depth=m.depth||'standard';return {action,depth,reason:m.reason||'',class_name:r.class_name||'?',from_level:r.start_level,to_level:r.end_level,level:r.start_level}}
function jobLabel(j){const x=jobIntent(j);if(x.action==='deepen_level')return `${x.class_name} L${x.level} · deepen (${x.depth})`;if(x.action==='investigate_level')return `${x.class_name} L${x.level} · investigate (${x.depth})`;return `${x.class_name} L${x.from_level||'?'}→${x.to_level||'?'} · recompute (${x.depth})`}
function ageText(ts){const n=Number(ts||0);if(!n)return '—';const d=Math.max(0,Date.now()/1000-n);if(d<60)return `${Math.round(d)}s ago`;if(d<3600)return `${Math.round(d/60)}m ago`;if(d<86400)return `${Math.round(d/3600)}h ago`;return `${Math.round(d/86400)}d ago`}
function producerVersionFromRequest(req){return String((req?.config||{}).producer_version||'').trim()}
function versionTag(version){return version?`v${version}`:'unknown version'}
function isCurrentProducer(req,currentVersion){const v=producerVersionFromRequest(req);return !!v && v===String(currentVersion||CURRENT_SOFTWARE_VERSION)}
function renderPublications(s){
  const box=$('publicationList'),scope=$('publicationScope');if(!box)return;
  const cls=state.cls,currentVersion=String(s.service_version||CURRENT_SOFTWARE_VERSION);
  const all=(s.publications||[]).filter(p=>(p.request||{}).class_name===cls);
  const current=all.filter(p=>isCurrentProducer(p.request,currentVersion));
  const legacy=all.filter(p=>!isCurrentProducer(p.request,currentVersion));
  if(scope)scope.textContent=`${classLabel(cls)} · current v${currentVersion}`;
  function row(p,legacyMode=false,staleFallback=false){
    const req=p.request||{},build=req.ruleset==='forever'?(req.forever_build_as_of||'2026-10-02 · legacy ≤.73'):'',producer=producerVersionFromRequest(req);
    const status=staleFallback?badge(`STALE · ${versionTag(producer)}`,'warn'):(legacyMode?badge(`legacy · ${versionTag(producer)}`,'warn'):badge('published','good'));
    return `<div class="pub-row"><b>${esc(jobLabel({request:req}))}</b> ${status} <span class="muted">${esc(String(p.id||'').slice(0,8))} · ${esc(ageText(p.created_at))}</span><div class="muted">job ${esc(String(p.job_id||'').slice(0,8))} · attempt ${esc(String(p.attempt_id||'').slice(0,8))} · producer ${esc(producer||'unknown')}${build?` · Forever ${esc(build)}`:''}</div></div>`
  }
  let html='';
  if(current.length) html+=current.slice(0,12).map(p=>row(p,false,false)).join('');
  else if(legacy.length) html+=`<div class="warn small" style="padding:5px 0">No publication from current v${esc(currentVersion)} yet. Showing latest older result only as stale fallback.</div>${row(legacy[0],true,true)}`;
  else html=`<span class="muted">No published ${esc(classLabel(cls))} result yet. A running or failed job does not replace the last good publication.</span>`;
  if(legacy.length){
    if(legacyPublicationsExpanded){
      const rows=(current.length?legacy:legacy.slice(1)).slice(0,40);
      if(rows.length)html+=rows.map(p=>row(p,true,false)).join('');
      html+=`<div class="small muted" style="padding:7px 3px">${legacy.length} result${legacy.length===1?'':'s'} from older/unknown versions · <button data-publication-history-toggle="1">collapse</button></div>`;
    }else{
      html+=`<div class="small muted" style="padding:7px 3px">${legacy.length} result${legacy.length===1?'':'s'} from older/unknown versions · <button data-publication-history-toggle="1">show</button></div>`;
    }
  }
  box.innerHTML=html;
}
function syncIntentControls(){const action=$('jobAction').value,single=action!=='recompute_range';$('jobEnd').disabled=single;if(single)$('jobEnd').value=$('jobStart').value;const depth=$('jobDepth');if(action==='deepen_level'&&depth.value==='standard')depth.value='wide';if(action==='investigate_level'&&depth.value!=='deep')depth.value='deep'}
function setCloneSource(j){cloneSourceJob=j;const el=$('cloneSource'),btn=$('clearClone'),q=$('enqueueJob');if(!j){el.textContent='';btn.style.display='none';q.textContent='Run request';return}const r=j.request||{},x=jobIntent(j);state.cls=r.class_name||state.cls;syncState();$('classPick').value=state.cls;$('jobAction').value=x.action;$('jobStart').value=r.start_level??11;$('jobEnd').value=r.end_level??state.target;$('jobDepth').value=x.depth;$('jobWorkers').value=Number((r.config||{}).workers||2);$('jobPriority').value=Number(j.priority||0);syncIntentControls();el.textContent=`rerun ${j.id.slice(0,10)} · edit request above`;btn.style.display='inline-block';q.textContent='Run edited request'}
function queuedOrder(s){return (s.jobs||[]).filter(j=>j.state==='queued').sort((a,b)=>Number(b.priority||0)-Number(a.priority||0)||Number(a.position||0)-Number(b.position||0)).map(j=>j.id)}
function queueRelevantJobs(jobs){
  const currentVersion=activeServiceVersion;
  const active=[], historical=[];
  for(const j of jobs){(['running','queued','paused'].includes(String(j.state||''))?active:historical).push(j)}
  historical.sort((a,b)=>Number(b.finished_at||b.updated_at||b.created_at||0)-Number(a.finished_at||a.updated_at||a.created_at||0));
  const currentHistory=historical.filter(j=>isCurrentProducer(j.request,currentVersion));
  const legacyHistory=historical.filter(j=>!isCurrentProducer(j.request,currentVersion));
  const keep=new Set(), currentClass=String(state.cls||'').toLowerCase();
  for(const j of currentHistory){
    if(hiddenProcessingJobs.has(j.id))continue;
    const st=String(j.state||'');
    if(st==='failed' && Array.from(keep).filter(id=>currentHistory.find(x=>x.id===id)?.state==='failed').length<2)keep.add(j.id);
  }
  let completedForClass=0;
  for(const j of currentHistory){
    if(hiddenProcessingJobs.has(j.id) || keep.has(j.id))continue;
    const x=jobIntent(j), sameClass=String(x.class_name||'').toLowerCase()===currentClass;
    if(j.state==='completed' && sameClass && completedForClass<2){keep.add(j.id);completedForClass++}
  }
  const visibleHistory=processingHistoryExpanded?historical:currentHistory.filter(j=>keep.has(j.id));
  const hiddenHistory=historical.filter(j=>!visibleHistory.some(v=>v.id===j.id));
  return {visible:active.concat(visibleHistory),hidden:hiddenHistory,legacyHidden:legacyHistory.filter(j=>!visibleHistory.some(v=>v.id===j.id)),activeIds:new Set(active.map(j=>j.id)),currentVersion};
}
function renderJobs(s){
  const box=$('jobList');if(!box)return;
  const hasStaleData=!!((s.jobs||[]).length || (s.publications||[]).length);
  if(!s.available && !hasStaleData){box.innerHTML='<div class="bad">Service offline</div>';return}
  activeServiceVersion=String(s.service_version||CURRENT_SOFTWARE_VERSION);
  const all=(s.jobs||[]).slice(0,100), filtered=queueRelevantJobs(all), jobs=filtered.visible;
  function row(j){
    const ev=j.latest_event||s.latest_events?.[j.id],cp=j.latest_checkpoint,att=j.latest_attempt,st=String(j.state||''),hb=j.heartbeat||{};
    const controls=st==='running'?['checkpoint','pause','cancel']:st==='queued'?['pause','cancel']:st==='paused'?['resume','cancel']:[];
    const heartbeat=hb.age_seconds!=null?`heartbeat ${Math.round(Number(hb.age_seconds))}s ago`:(att?.heartbeat_at?`heartbeat ${ageText(att.heartbeat_at)}`:'');
    const checkpoint=cp?`checkpoint ${ageText(cp.created_at)} · ${cp.kind||'state'}`:'no checkpoint';
    const prog=j.progress||{mode:'indeterminate'},determinate=prog.mode==='determinate'&&Number.isFinite(Number(prog.fraction)),pct=determinate?Math.max(0,Math.min(100,Number(prog.fraction)*100)):null;
    const progressHtml=determinate?`<div class="job-progress"><div class="small muted">${esc(j.phase||st)}${j.stage?` · ${esc(j.stage)}`:''} · ${pct.toFixed(0)}%${prog.current!=null&&prog.total!=null?` (${esc(prog.current)}/${esc(prog.total)} ${esc(prog.unit||'')})`:''}</div><div class="progress-track"><div class="progress-fill" style="width:${pct.toFixed(1)}%"></div></div></div>`:`<div class="job-progress small muted">${esc(j.phase||st)}${j.stage?` · ${esc(j.stage)}`:''} · progress indeterminate${j.runtime_level!=null?` · L${esc(j.runtime_level)}`:''}</div>`;
    const best=j.best_so_far?.best_validated_hours!=null?`best ${Number(j.best_so_far.best_validated_hours).toFixed(3)} h${j.best_so_far.candidate_id?` · ${esc(String(j.best_so_far.candidate_id).slice(0,8))}`:''}`:'best —',q=st==='queued',active=filtered.activeIds.has(j.id);
    const producer=producerVersionFromRequest(j.request),legacy=!active&&!isCurrentProducer(j.request,filtered.currentVersion);
    return `<div class="job-row ${hb.stalled?'stalled':''}"><div><b>${esc(jobLabel(j))}</b> ${badge(st,`state-${st}`)} ${badge('p'+Number(j.priority||0))}${legacy?badge(`legacy · ${versionTag(producer)}`,'warn'):''}${hb.stalled?badge('stalled','bad'):''}<div class="small muted">${esc(j.id.slice(0,10))} · attempt ${esc(j.attempt_count||0)}${att?.id?` · attempt ${esc(String(att.id).slice(0,8))}`:''}${j.latest_publication?.id?` · publication ${esc(String(j.latest_publication.id).slice(0,8))}`:''} · producer ${esc(producer||'unknown')}${j.control_requested?` · control pending: ${esc(j.control_requested)}`:''}</div>${progressHtml}<div class="job-meta small muted"><span>${esc(best)}</span>${ev?`<span>event ${esc(ev.kind)} · ${esc(ageText(ev.created_at))}</span>`:''}${heartbeat?`<span>${esc(heartbeat)}</span>`:''}<span>${esc(checkpoint)}</span></div>${j.runtime_message?`<div class="small muted" style="margin-top:3px">${esc(j.runtime_message)}</div>`:''}</div><div class="job-actions">${controls.map(a=>`<button data-job-action="${a}" data-job-id="${esc(j.id)}">${a==='checkpoint'?'checkpoint now':a}</button>`).join('')}${q?`<button data-job-action="reorder_up" data-job-id="${esc(j.id)}">↑</button><button data-job-action="reorder_down" data-job-id="${esc(j.id)}">↓</button>`:''}<button data-job-action="history" data-job-id="${esc(j.id)}">history</button><button data-job-action="saved_states" data-job-id="${esc(j.id)}">saved states</button><button data-job-action="clone" data-job-id="${esc(j.id)}">rerun/edit</button>${active?'':`<button data-job-action="hide_local" data-job-id="${esc(j.id)}">hide</button>`}</div></div>`;
  }
  const legacyCount=filtered.legacyHidden.length,otherHidden=Math.max(0,filtered.hidden.length-legacyCount);
  const hiddenLabel=[legacyCount?`${legacyCount} older-version run${legacyCount===1?'':'s'}`:'',otherHidden?`${otherHidden} other hidden run${otherHidden===1?'':'s'}`:''].filter(Boolean).join(' · ');
  const historyLine=processingHistoryExpanded?`<div class="small muted" style="padding:7px 3px">${Math.max(0,all.length-filtered.activeIds.size)} history runs · <button data-history-toggle="1">collapse</button></div>`:(filtered.hidden.length?`<div class="small muted" style="padding:7px 3px">hidden runs · ${hiddenLabel||filtered.hidden.length} · <button data-history-toggle="1">show</button></div>`:'');
  const outageNote=!s.available?'<div class="bad small" style="padding:6px 3px">Service offline · showing last known state</div>':(s.degraded?'<div class="warn small" style="padding:6px 3px">Service delayed · showing last known state</div>':'');
  box.innerHTML=outageNote+(jobs.length?jobs.map(row).join(''):'<div class="muted">Queue empty.</div>')+historyLine;
  renderPublications(s)
}
async function loadServiceStatus(){
  if(servicePollInFlight)return;
  servicePollInFlight=true;
  const el=$('serviceStatus'),msg=$('serviceMessage'),meta=$('serviceMeta');
  try{
    const r=await fetch('/api/service',{cache:'no-store'}),j=await r.json();
    lastServiceSnapshot=j;
    const publicationId=String(j.latest_publication?.id||'');
    if(j.available && !j.stale){
      if(decisionsPublicationId===null){decisionsPublicationId=publicationId}
      else if(publicationId!==decisionsPublicationId){decisionsPublicationId=publicationId;queuedNativeView=null;await reloadDecisions()}
    }
    if(el)el.textContent=j.available?(j.degraded?'service delayed':`service · ${j.active_count||0} active`):'service offline';
    if(msg)msg.textContent=j.available?(j.degraded?`Transient service delay · keeping last known queue (${j.consecutive_failures||1} missed poll${Number(j.consecutive_failures||1)===1?'':'s'})`:`${j.active_count||0} active · ${j.jobs?.length||0} known jobs · ${j.service_url||''}`):(j.error||'service offline');
    if(meta){
      const ir=j.item_refresh,irs=ir?` · item refresh ${ir.state}${ir.result?.canonical_items!=null?` · ${ir.result.canonical_items} items`:''}${ir.error?` · ${ir.error}`:''}`:'';
      meta.textContent=(j.available||j.stale)?`API v${j.api_version||'?'} · DB schema ${j.schema_version||'?'} · latest publication ${j.latest_publication?ageText(j.latest_publication.created_at):'none'}${j.stale?` · stale ${Math.round(Number(j.stale_for_seconds||0))}s`:''}${irs}`:'';
      const b=$('refreshItemsButton');if(b)b.disabled=!!ir&&['queued','capturing','building','publishing'].includes(ir.state);
      const o=$('refreshItemsResult');if(o&&ir){o.textContent=ir.state==='completed'?`Refresh complete · ${ir.result?.canonical_items||'?'} canonical items`:ir.state==='failed'?`Refresh failed · ${ir.error||'unknown error'}`:`Refresh ${ir.state}…`}
      renderAbilityCapture(j.abilities_capture);
    }
    renderJobs(j);
    void pollNativeQueueStatus();
  }catch(e){
    const j=lastServiceSnapshot;
    if(j){const stale={...j,available:false,degraded:true,stale:true,error:String(e)};if(el)el.textContent='service offline';if(msg)msg.textContent=String(e);renderJobs(stale)}
    else{if(el)el.textContent='service offline';if(msg)msg.textContent=String(e);if(meta)meta.textContent='';renderJobs({available:false})}
  }finally{servicePollInFlight=false}
}
async function enqueueSelectedJob(){const msg=$('serviceMessage'),action=$('jobAction').value,start=Number($('jobStart').value),end=Number($('jobEnd').value||start),depth=$('jobDepth').value,workers=Math.max(1,Number($('jobWorkers').value||2)),priority=Number($('jobPriority').value||0);let body={action,class_name:state.cls,depth,workers,priority,deduplicate:!cloneSourceJob};if(action==='recompute_range'){if(end<start){msg.textContent='Rejected: end level must be >= start level.';return}body.from_level=start;body.to_level=end}else body.level=start;msg.textContent='Pending: request…';try{const path='/api/service/intents';const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);msg.textContent=`Accepted: ${j.summary||jobLabel(j.job)} · ${j.job.id.slice(0,10)}`;setCloneSource(null);await loadServiceStatus()}catch(e){msg.textContent='Rejected: '+e}}
function renderAbilityCapture(status){
  const c=status?.catalogue||{},task=status?.refresh||{},summary=$('abilitiesCatalogueStatus'),out=$('abilitiesRefreshResult');
  const active=['queued','capturing','verifying','publishing'].includes(task.state);
  $('refreshAbilitiesButton').disabled=active||!status||!!status.error;
  $('fetchAbilityDetailsButton').disabled=active||!c.index_complete||!!status?.error;
  if(status?.error){summary.textContent='Service endpoint unavailable';out.textContent=String(status.error);return}
  if(!c.present){summary.textContent='No catalogue yet';out.textContent='Refresh all 9 indexes to create the canonical source catalogue.';return}
  summary.textContent=`${c.index_complete?'Index complete':'Index incomplete'} · ${Number(c.lists||0)}/18 lists · ${Number(c.rows||0)} records · ${Number(c.details_verified||0)}/${Number(c.unique_spells||0)} unique spell tooltips · batch ${String(c.batch_id||'—')}`;
  if(task.id){
    if(task.state==='failed'||task.state==='interrupted')out.textContent=`Capture ${task.state} · ${task.error||'see server log'} · active catalogue unchanged`;
    else if(['completed','completed_with_warnings'].includes(task.state))out.textContent=`Capture ${task.state} · ${task.mode} · +${Number(task.result?.new_details||0)} verified tooltips · ${Number(task.result?.rows||c.rows||0)} rows · ${Number(task.result?.detail_failures||0)} tooltip errors · item catalogue untouched`;
    else out.textContent=`Capture ${task.state}… · ${task.mode} · ${Number(task.progress?.done||0)}/${Number(task.progress?.total||0)} processed${task.progress?.last_step?' · '+task.progress.last_step:''} · previous catalogue stays available`;
  }else out.textContent='Raw source index only · talent grid, prerequisite geometry and executable effects are separate verification steps.';
}
async function refreshAbilityData(mode){
  const out=$('abilitiesRefreshResult'),button=$(mode==='details'?'fetchAbilityDetailsButton':'refreshAbilitiesButton');
  const question=mode==='index'?'Refresh all 9 Forever class ability/talent lists? A Chrome window will open. The verified current catalogue is preserved if capture fails.':'Fetch the next 20 missing spell/talent tooltips using the same Chrome profile?';
  if(!window.confirm(question))return;
  out.textContent='Submitting '+(mode==='index'?'class index':'tooltip')+' capture…';button.disabled=true;
  try{
    const body=mode==='index'?{mode:'index'}:{mode:'details',max_details:20};
    const r=await fetch('/api/service/abilities/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),j=await r.json();
    if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);
    out.textContent=`Capture queued · ${String(j.refresh?.id||'').slice(0,8)}`;await loadServiceStatus();
  }catch(e){out.textContent='Capture rejected: '+e;button.disabled=false}
}
async function refreshAllItems(){const out=$('refreshItemsResult'),btn=$('refreshItemsButton');if(!window.confirm('Refresh the full Mage/Druid/Paladin/Hunter Wowhead item catalogue? A visible Chrome window will open.'))return;out.textContent='Starting full item refresh…';btn.disabled=true;try{const r=await fetch('/api/service/items/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({classes:['mage','druid','paladin','hunter']})}),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);out.textContent=`Refresh started · ${String(j.refresh?.id||'').slice(0,8)}`;await loadServiceStatus()}catch(e){out.textContent='Rejected: '+e;btn.disabled=false}}
async function addSelectedItem(){const input=$('addItemInput'),out=$('addItemResult'),value=String(input.value||'').trim();if(!value){out.textContent='Enter an item ID or Wowhead Forever URL.';return}out.textContent='Fetching exact Wowhead item…';try{const r=await fetch('/api/service/items/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item:value,class_name:state.cls})}),j=await r.json();if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);const req=j.effective_required_level==null?'?':j.effective_required_level,ranges=j.affected_ranges||{},parts=Object.keys(ranges).sort().map(cls=>`${cls} L${ranges[cls][0]}–${ranges[cls][1]}`),affected=parts.length?parts.join(', '):'no modeled levels';out.textContent=`Added ${j.name} (#${j.item_id}) · ${j.slot||'slot ?'} · effective req L${req} · eligible: ${affected}`;input.value=''}catch(e){out.textContent='Rejected: '+e}}
function renderSavedStates(jobId,states){const box=$('savedStatePanel');box.style.display='block';const rows=states||[];box.innerHTML=`<div class="route-head"><b>Saved states · ${esc(jobId.slice(0,10))}</b><button type="button" onclick="document.getElementById('savedStatePanel').style.display='none'">Close</button></div>`+(rows.length?rows.map(cp=>{const mode=String(cp.compatibility||'incompatible'),why=(cp.reasons||[]).join(', '),a=cp.actions||{},seedWhy=cp.seed_unavailable_reason?` · ${esc(cp.seed_unavailable_reason)}`:'';return `<div class="job-row"><div><b>${esc(mode)}</b> ${badge(mode,mode==='resume'?'good':(mode==='seed_only'?'warn':'bad'))}<div class="small muted">${esc(cp.id.slice(0,10))} · ${esc(ageText(cp.created_at))} · ${esc(why)}${seedWhy}</div></div><div class="job-actions">${a.resume?`<button data-saved-mode="resume" data-job-id="${esc(jobId)}" data-checkpoint-id="${esc(cp.id)}">Resume from this</button>`:''}${mode==='seed_only'?`<button data-saved-mode="seed_only" data-job-id="${esc(jobId)}" data-checkpoint-id="${esc(cp.id)}" ${a.seed_only?'':'disabled'}>Use as seed</button>`:''}${mode==='incompatible'?'<span class="small bad">cannot load</span>':''}</div></div>`}).join(''):'<div class="muted">No saved checkpoints available.</div>')}
function renderLineage(v){const box=$('lineagePanel');if(!box)return;box.style.display='block';const j=v.job||{},rows=v.attempts||[];box.innerHTML=`<div class="route-head"><b>Lineage · ${esc(String(j.id||'').slice(0,10))}</b><span class="small muted">${esc(v.publication_count||0)} publication(s)</span></div>${rows.length?rows.map(a=>`<div class="pub-row"><b>attempt ${esc(a.ordinal||'?')} · ${esc(a.state||'?')}</b> <span class="muted">${esc(String(a.id||'').slice(0,8))}</span><div class="muted">${(a.checkpoints||[]).length} checkpoint(s) · ${(a.publications||[]).length} publication(s)${(a.publications||[])[0]?` · latest ${esc(ageText((a.publications||[])[0].created_at))}`:''}</div></div>`).join(''):'<div class="muted">No attempts yet.</div>'}`}
async function loadLineage(id){const msg=$('serviceMessage');msg.textContent=`Loading lineage · ${id.slice(0,10)}`;try{const r=await fetch(`/api/service/jobs/${encodeURIComponent(id)}/lineage`,{cache:'no-store'}),v=await r.json();if(!r.ok)throw new Error(v.error||`HTTP ${r.status}`);renderLineage(v);msg.textContent=`Lineage loaded · ${id.slice(0,10)}`}catch(e){msg.textContent='Rejected: '+e}}
async function loadSavedStates(id){const msg=$('serviceMessage');msg.textContent=`Loading saved states · ${id.slice(0,10)}`;try{const r=await fetch(`/api/service/jobs/${encodeURIComponent(id)}/saved-states`,{cache:'no-store'}),v=await r.json();if(!r.ok)throw new Error(v.error||`HTTP ${r.status}`);renderSavedStates(id,v.saved_states||[]);msg.textContent=`Saved-state compatibility loaded · ${id.slice(0,10)}`}catch(e){msg.textContent='Rejected: '+e}}
async function selectSavedState(id,checkpointId,mode){const msg=$('serviceMessage');msg.textContent=`Pending: ${mode} · ${checkpointId.slice(0,10)}`;try{const r=await fetch(`/api/service/jobs/${encodeURIComponent(id)}/saved-state`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({checkpoint_id:checkpointId,mode})}),v=await r.json();if(!r.ok)throw new Error(v.error||`HTTP ${r.status}`);msg.textContent=`Accepted: ${mode} · ${checkpointId.slice(0,10)}; job queued`;await loadServiceStatus();await loadSavedStates(id)}catch(e){msg.textContent='Rejected: '+e}}
async function controlJob(id,action){const msg=$('serviceMessage');msg.textContent=`Pending: ${action} · ${id.slice(0,10)}`;try{const snap=await (await fetch('/api/service',{cache:'no-store'})).json(),job=(snap.jobs||[]).find(x=>x.id===id);if(!job)throw new Error('job disappeared');if(action==='history'){await loadLineage(id);return}if(action==='saved_states'){await loadSavedStates(id);return}if(action==='clone'){setCloneSource(job);msg.textContent=`Accepted: clone source ${id.slice(0,10)} loaded; edit overrides then Queue clone`;return}let path=`/api/service/jobs/${encodeURIComponent(id)}/${action}`,body={};if(action==='reorder_up'||action==='reorder_down'){const ids=queuedOrder(snap),i=ids.indexOf(id),j=i+(action==='reorder_up'?-1:1);if(i<0||j<0||j>=ids.length)throw new Error('job already at queue boundary');[ids[i],ids[j]]=[ids[j],ids[i]];path='/api/service/queue/reorder';body={job_ids:ids}}const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),v=await r.json();if(!r.ok)throw new Error(v.error||`HTTP ${r.status}`);msg.textContent=`Accepted: ${action} · ${id.slice(0,10)}${action==='checkpoint'?'; waiting for safe checkpoint boundary':''}`;await loadServiceStatus()}catch(e){msg.textContent='Rejected: '+e}}
async function load(){await reloadDecisions();restoreNativeQueueJob();bind();await loadServiceStatus();loadRuntimeStatus();setInterval(loadServiceStatus,2000);setInterval(loadRuntimeStatus,2000)}
load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);
</script></body></html>'''
DECISIONS_HTML = DECISIONS_HTML.replace('__SOFTWARE_VERSION__', SOFTWARE_VERSION)



def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _cached_seed(path: Path):
    try:
        stat = path.stat()
        sig = (stat.st_mtime_ns, stat.st_size)
        old = _SEED_CACHE.get(path)
        if old and old[0] == sig:
            return old[1]
        obj = read_json(path, None)
        if obj is not None:
            _SEED_CACHE[path] = (sig, obj)
        return obj
    except OSError:
        return None


def _decorate_seed_candidate(raw: dict, level: int | None = None):
    c = dict(raw)
    if level is not None:
        for k, v in opt.objective_level_meta(level).items(): c.setdefault(k, v)
    c['rotation_details'] = sm.rotation_details(c.get('policy') or '')
    return c


def _active_school() -> str:
    try:
        status=read_json(sm.RUNTIME / 'status.json', {})
        return sm.eng.normalize_primary_school(status.get('school','all'))
    except Exception:
        return 'all'


def seed_level_summaries(water_mode: str = 'buy_water', school: str | None = None):
    out = []
    school=_active_school() if school is None else sm.eng.normalize_primary_school(school)
    seed_dir = sm.school_seed_dir(water_mode,school)
    if not seed_dir.exists():
        return out
    for path in sorted(seed_dir.glob('lvl_*.json')):
        obj = _cached_seed(path)
        if not obj:
            continue
        candidates = obj.get('candidates') or []
        if not candidates:
            continue
        out.append({
            'level': obj.get('level'),
            'mode': obj.get('mode'),
            'candidate_count': len(candidates),
            'best': _decorate_seed_candidate(candidates[0], int(obj.get('level'))),
        })
    return out


def seed_bank(level: int, water_mode: str = 'buy_water', school: str | None = None):
    if level < 11 or level > 60:
        return None
    school=_active_school() if school is None else sm.eng.normalize_primary_school(school)
    obj = _cached_seed(sm.school_seed_dir(water_mode,school) / f'lvl_{level:02d}.json')
    if obj is None:
        return None
    out = dict(obj)
    lvl = int(obj.get('level') or level)
    out.setdefault('meta', {}).update({k:v for k,v in opt.objective_level_meta(lvl).items() if k not in out.get('meta', {})})
    out['candidates'] = [_decorate_seed_candidate(c, lvl) for c in (obj.get('candidates') or [])]
    return out


def snapshot(water_mode: str = 'buy_water'):
    """Tiny pre-aggregated live snapshot; request path performs no DB scans."""
    water_mode = sm.normalize_water_mode(water_mode)
    path = sm.viewer_snapshot_path(water_mode)
    obj = read_json(path, None) if path.exists() else None
    if obj is not None:
        return obj
    # First run / old state fallback. Still uses O(1) cache stats and then writes
    # the snapshot so subsequent browser refreshes are a single small-file read.
    obj = sm.viewer_snapshot_payload(water_mode)
    sm.publish_viewer_snapshot(water_mode, obj.get('status') or {})
    return obj



def fast_snapshot():
    """Read-only analytic/Fast snapshot, isolated under state/v2."""
    return fast_state.read_snapshot()


def decision_snapshot(level: int | None = None, backend_id: str | None = None,
                      class_name: str | None = None):
    """Read decisions from the service-owned publication authority.

    The service owns scheduler attempts and publication manifests, so an attached
    listener must not independently resolve its own local ``state/`` tree.  A
    local fallback is retained only for standalone/offline listener use.
    """
    try:
        if hasattr(_SERVICE_CLIENT, "decisions"):
            return _SERVICE_CLIENT.decisions(level=level, backend_id=backend_id,
                                             class_name=class_name)
    except ServiceClientError:
        # Never silently run an expensive local optimizer when the authoritative
        # service is unavailable. Offline mode must be an explicit operator choice.
        if os.environ.get("WOW_LISTENER_OFFLINE_DECISIONS") != "1":
            raise
    if os.environ.get("WOW_LISTENER_OFFLINE_DECISIONS") == "1":
        return build_decision_payload(selected_level=level, backend_id=backend_id,
                                      class_name=class_name)
    raise ServiceClientError("optimizer service decisions endpoint is unavailable")


def landscape_snapshot(water_mode: str='buy_water', limit: int=1200):
    """Bounded full-path snapshot; no per-level scenario rows are exposed."""
    water_mode=sm.normalize_water_mode(water_mode); limit=max(50,min(4000,int(limit)))
    key=(water_mode,limit,pnp_cache.current_sim_hash()); now=time.monotonic()
    with _LANDSCAPE_LOCK:
        old=_LANDSCAPE_CACHE.get(key)
        if old and now-old[0] < 10.0:
            return old[1]
    obj=pnp_cache.landscape_points(water_mode,limit)
    with _LANDSCAPE_LOCK:
        _LANDSCAPE_CACHE[key]=(now,obj)
    return obj


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/api/runtime':
            body=json.dumps(local_runtime_snapshot(),ensure_ascii=False,separators=(',',':')).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/api/service':
            body=json.dumps(service_snapshot(),ensure_ascii=False,separators=(',',':')).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path.startswith('/api/service/jobs/') and len(path.split('/'))==5:
            job_id=path.rsplit('/',1)[-1]
            if not re.fullmatch(r'[a-f0-9]{32}',job_id):
                self.send_error(400,'invalid job ID');return
            try:
                job=_SERVICE_CLIENT.get_job(job_id)
                body=json.dumps(job,ensure_ascii=False,separators=(',',':')).encode('utf-8');status=200
            except ServiceClientError as exc:
                body=json.dumps({'error':str(exc),'legacy_fallback':False}).encode('utf-8');status=503
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        if path.startswith('/api/service/jobs/') and path.endswith('/saved-states'):
            try:
                parts=[x for x in path.split('/') if x]; job_id=parts[3]
                body=json.dumps({'saved_states':_SERVICE_CLIENT.saved_states(job_id)},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except ServiceClientError as e:
                body=json.dumps({'error':str(e)},ensure_ascii=False,separators=(',',':')).encode('utf-8'); self.send_response(503); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path.startswith('/api/service/jobs/') and path.endswith('/lineage'):
            try:
                parts=[x for x in path.split('/') if x]; job_id=parts[3]
                body=json.dumps(_SERVICE_CLIENT.lineage(job_id),ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except ServiceClientError as e:
                body=json.dumps({'error':str(e)},ensure_ascii=False,separators=(',',':')).encode('utf-8'); self.send_response(503); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/api/decisions/queued':
            qs=parse_qs(parsed.query)
            cls=(qs.get('class') or [''])[0]; backend=(qs.get('backend') or [''])[0]
            try:
                level=int((qs.get('level') or [''])[0])
                from src.game.data.forever.queue_capabilities import require_native_generic_queue
                if backend != 'generic':
                    raise ValueError('queued Decision requires explicit generic backend')
                require_native_generic_queue(cls,level)
                payload=_SERVICE_CLIENT.queued_generic_decision(
                    class_name=cls,level=level,backend_id=backend)
            except (TypeError,ValueError) as exc:
                body=json.dumps({'error':str(exc)}).encode('utf-8');self.send_response(400)
            except ServiceClientError as exc:
                body=json.dumps({'error':str(exc),'legacy_fallback':False}).encode('utf-8');self.send_response(503)
            else:
                body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8');self.send_response(200)
            self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        if path == '/api/decisions':
            qs=parse_qs(parsed.query)
            try: level=int((qs.get('level') or [''])[0]) if qs.get('level') else None
            except (TypeError,ValueError):
                self.send_error(400,'level must be an integer'); return
            backend=(qs.get('backend') or [None])[0]
            if backend is not None and backend not in {'legacy','generic','compare'}:
                self.send_error(400,'backend must be legacy, generic or compare'); return
            cls=(qs.get('class') or [None])[0]
            try:
                decision_data = decision_snapshot(level,backend,cls)
            except ServiceClientError as exc:
                body=json.dumps({'error':str(exc),'service_authority':'unavailable','offline_fallback':False},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(503); self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            body=json.dumps(decision_data,ensure_ascii=False,separators=(',',':')).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/decisions':
            body=DECISIONS_HTML.encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store, no-cache, must-revalidate'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/api/fast':
            body=json.dumps(fast_snapshot(),ensure_ascii=False,separators=(',',':')).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/fast':
            body=FAST_HTML.encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store, no-cache, must-revalidate'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/api/landscape':
            qs=parse_qs(parsed.query); water_mode=sm.normalize_water_mode((qs.get('water') or ['buy_water'])[0])
            try: limit=int((qs.get('limit') or ['1200'])[0])
            except (TypeError,ValueError): limit=1200
            body=json.dumps(landscape_snapshot(water_mode,limit),ensure_ascii=False,separators=(',',':')).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/api/state':
            qs = parse_qs(parsed.query)
            water_mode = sm.normalize_water_mode((qs.get('water') or ['buy_water'])[0])
            school = (qs.get('school') or [None])[0]
            body = json.dumps(snapshot(water_mode), ensure_ascii=False).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/api/seeds':
            qs = parse_qs(parsed.query)
            water_mode = sm.normalize_water_mode((qs.get('water') or ['buy_water'])[0])
            school = (qs.get('school') or [None])[0]
            try:
                level = int((qs.get('level') or [''])[0])
            except (TypeError, ValueError):
                self.send_error(400, 'level must be an integer'); return
            obj = seed_bank(level, water_mode, school)
            if obj is None:
                self.send_error(404, 'seed bank not available yet'); return
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/landscape':
            body=LANDSCAPE_HTML.encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store, no-cache, must-revalidate'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == '/':
            body = HTML.encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store, no-cache, must-revalidate'); self.send_header('Pragma','no-cache')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_error(404)
    def do_POST(self):
        parsed=urlparse(self.path)
        if parsed.path == '/api/runtime/command':
            try:
                n=int(self.headers.get('Content-Length','0') or 0)
                if n < 0 or n > 4096: raise ValueError('request body too large')
                raw=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                result=request_local_runtime(str(raw.get('command') or ''),str(self.headers.get('X-Local-Stack-Token') or ''))
                body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except Exception as e:
                body=json.dumps({'error':str(e)},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(400); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path in {'/api/service/intents','/api/service/items/add','/api/service/items/refresh','/api/service/abilities/refresh','/api/service/jobs','/api/service/queue/reorder'} or parsed.path.startswith('/api/service/jobs/'):
            try:
                n=int(self.headers.get('Content-Length','0') or 0)
                if n < 0 or n > 1_048_576: raise ValueError('request body too large')
                raw=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                if not isinstance(raw,dict): raise ValueError('JSON body must be an object')
                parts=[x for x in parsed.path.split('/') if x]
                if parsed.path == '/api/service/intents':
                    allowed={'action','class_name','class','from_level','to_level','start_level','end_level','level','depth','reason','priority','deduplicate'}
                    body_in={k:v for k,v in raw.items() if k in allowed}
                    result=_SERVICE_CLIENT.submit_intent(body_in)
                    body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                elif parsed.path == '/api/service/items/refresh':
                    classes=raw.get('classes')
                    if classes is not None and not isinstance(classes,list): raise ValueError('classes must be an array')
                    result=_SERVICE_CLIENT.refresh_items(classes)
                    body=json.dumps({'refresh':result},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                elif parsed.path == '/api/service/abilities/refresh':
                    if set(raw) - {'mode','max_details'}: raise ValueError('unknown abilities capture options')
                    result=_SERVICE_CLIENT.refresh_abilities(mode=str(raw.get('mode','index')),
                        max_details=raw.get('max_details'))
                    body=json.dumps({'refresh':result},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                elif parsed.path == '/api/service/items/add':
                    value=raw.get('item',raw.get('item_id',raw.get('url')))
                    result=_SERVICE_CLIENT.add_item(value,class_name=str(raw.get('class_name') or raw.get('class') or '') or None)
                    body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                elif parsed.path == '/api/service/jobs':
                    allowed={'ruleset','class_name','start_level','end_level','objective','endpoint_mode','source_snapshot','engine_semantic_hash','policy_space_version','forever_build_as_of','config','validation_modes','priority','deduplicate'}
                    body_in={k:v for k,v in raw.items() if k in allowed}
                    job,created=_SERVICE_CLIENT.enqueue(body_in)
                    body=json.dumps({'created':created,'job':job},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                elif parsed.path == '/api/service/queue/reorder':
                    ids=raw.get('job_ids')
                    if not isinstance(ids,list) or not all(isinstance(x,str) for x in ids): raise ValueError('job_ids must be an array of strings')
                    body=json.dumps({'jobs':_SERVICE_CLIENT.reorder(ids)},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                elif len(parts)==5 and parts[:3]==['api','service','jobs']:
                    job_id,action=parts[3],parts[4]
                    if action in {'pause','resume','cancel','checkpoint'}:
                        result=_SERVICE_CLIENT.control(job_id,action)
                        body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                    elif action=='saved-state':
                        result=_SERVICE_CLIENT.select_saved_state(job_id,str(raw.get('checkpoint_id') or ''),str(raw.get('mode') or ''))
                        body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                    elif action=='priority':
                        result=_SERVICE_CLIENT.set_priority(job_id,int(raw.get('priority')))
                        body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                    elif action=='clone':
                        job,created=_SERVICE_CLIENT.clone(job_id,overrides=raw.get('overrides') or {},priority=raw.get('priority'),deduplicate=bool(raw.get('deduplicate',False)))
                        body=json.dumps({'created':created,'job':job,'source_job_id':job_id},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                    else:
                        raise ValueError('unsupported service action')
                else:
                    raise ValueError('unsupported service endpoint')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except ServiceClientError as e:
                body=json.dumps({'error':str(e)},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(503); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except Exception as e:
                body=json.dumps({'error':str(e)},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(400); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path in {'/api/decisions/item-compare','/api/decisions/upgrade-search'}:
            try:
                n=int(self.headers.get('Content-Length','0') or 0)
                raw=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                class_name=str(raw.get('class') or '').lower()
                if class_name not in set(class_names('forever')): raise ValueError('unknown Forever class')
                weights=raw.get('weights') or {}
                if not isinstance(weights,dict): raise ValueError('weights must be an object')
                if parsed.path=='/api/decisions/item-compare':
                    result=compare_items(raw.get('item_a'),raw.get('item_b'),weights)
                else:
                    result=wowhead_upgrade_search(class_name,int(raw.get('level')),weights,slot=str(raw.get('slot') or '') or None)
                body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except Exception as e:
                body=json.dumps({'status':'error','error':str(e)},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(400); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path=='/api/decisions/compare-build':
            try:
                n=int(self.headers.get('Content-Length','0') or 0)
                raw=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                class_name=str(raw.get('class') or '').lower()
                if class_name not in set(class_names('forever')):
                    raise TalentsForeverBuildError('unknown Forever class')
                level=int(raw.get('level'))
                target_level=int(raw.get('target_level'))
                route=str(raw.get('route') or 'unconstrained')
                source_url=str(raw.get('source_url') or '')
                mode=str(raw.get('mode') or 'same_gear')
                decisions=decision_snapshot(level)
                result=compare_to_talentsforever_build(
                    decisions,class_name=class_name,target_level=target_level,route=route,
                    selected_level=level,source_url=source_url,mode=mode,
                )
                body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except TalentsForeverComparisonUnavailable as e:
                body=json.dumps({'status':'unavailable','error':str(e),'source_url':str((locals().get('raw') or {}).get('source_url') or '')},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except TalentsForeverBuildError as e:
                body=json.dumps({'status':'error','error':str(e)},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(400); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except Exception as e:
                body=json.dumps({'status':'error','error':str(e)},ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(400); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path=='/api/decisions/validate':
            try:
                n=int(self.headers.get('Content-Length','0') or 0)
                raw=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                if str(raw.get('class') or '')!='mage' or str(raw.get('question') or 'ice_lance')!='ice_lance':
                    raise ValueError('only Mage Ice Lance validation is currently supported')
                level=int(raw.get('level') or 20)
                if level<20 or level>60: raise ValueError('level must be 20..60')
                env=dict(os.environ); env['WOW_SIM_RULESET']='forever'; env['WOW_SIM_CLASS']='mage'
                cmd=[sys.executable,'-m','src.v2.mage_structural_validation','--level',str(level),'--n','32','--seed','7']
                proc=subprocess.run(cmd,cwd=str(sm.ROOT),env=env,capture_output=True,text=True,timeout=45,check=True)
                body=proc.stdout.strip().splitlines()[-1].encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except Exception as e:
                self.send_error(400,str(e)); return
        if parsed.path=='/api/decisions/constraint':
            try:
                n=int(self.headers.get('Content-Length','0') or 0)
                raw=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                class_name=str(raw.get('class') or '')
                allowed = set(class_names('forever'))
                if class_name not in allowed:
                    raise ValueError('class must be one of: ' + ', '.join(sorted(allowed)))
                level=int(raw.get('target_level'))
                frontier=read_json(resolve_published_path(sm.ROOT, Path("games") / f"forever-{class_name}" / "v2" / "decision_frontier.json"),{}) or {}
                constraint=dict(raw.get('constraint') or {})
                source_url=str(raw.get('source_url') or '').strip()
                source_allocation=None
                if source_url:
                    at_level=constraint.get('at_level')
                    if at_level is None:
                        raise ValueError('constraint.at_level is required with source_url')
                    source_allocation=talentsforever_allocation_at_level(
                        source_url, expected_class=class_name, selected_level=int(at_level),
                    )
                    constraint['at_level_talent_allocation_exact']=dict(source_allocation['talent_ranks'])
                result=analyze_constraint(frontier,level,constraint)
                if source_allocation is not None:
                    result['current_talents_source']=source_allocation
                if result.get('status')=='available' and (result.get('constraint') or {}).get('at_level') is not None:
                    dual_doc=read_published_class_artifact(sm.ROOT, Path("decisions") / "forever" / "dual_spec.json") or {}
                    dual_row=((dual_doc.get('classes') or {}).get(class_name) or {})
                    result['dual_spec_continuation']=dual_spec_continuation(dual_row,at_level=int(result['constraint']['at_level']),target_level=level)
                body=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            except Exception as e:
                self.send_error(400,str(e)); return
        if parsed.path!='/api/config':
            self.send_error(404); return
        try:
            n=int(self.headers.get('Content-Length','0') or 0)
            raw=json.loads(self.rfile.read(n).decode('utf-8') or '{}')
            cfg=sm.write_user_config(raw)
            body=json.dumps(cfg,ensure_ascii=False).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        except Exception as e:
            self.send_error(400,str(e))
    def log_message(self, fmt, *args): return


def _normalize_open_path(value: str) -> str:
    """Normalize an endpoint that may have crossed an MSYS/Git Bash boundary.

    Git Bash rewrites slash-prefixed command-line arguments before Python sees
    them, so ``/decisions`` can arrive as something like
    ``C:/Program Files/Git/decisions``.  Keep the accepted endpoint set tight:
    only known listener routes are recovered; arbitrary paths remain invalid
    and are still rejected by argparse's ``choices`` check.
    """
    raw = str(value or '/').replace('\\', '/')
    if raw in ('/', '/fast', '/decisions'):
        return raw
    lowered = raw.lower().rstrip('/')
    for endpoint in ('/decisions', '/fast'):
        if lowered.endswith(endpoint):
            return endpoint
    return raw


def main():
    ap=argparse.ArgumentParser(description='Read-only browser listener for Mage optimizer state')
    game_context.add_game_arguments(ap)
    ap.add_argument('--host',default='127.0.0.1'); ap.add_argument('--port',type=int,default=8765)
    ap.add_argument('--no-browser',action='store_true')
    ap.add_argument('--open-path',type=_normalize_open_path,
                    choices=('/', '/fast', '/decisions'),default='/')
    a=ap.parse_args(); sm.ensure_dirs(); sm.migrate_legacy_buy_water_state(); [sm.seed_baseline_if_needed(m) for m in sm.WATER_MODES]
    # G50d: the opt-in legacy-disabled service mode must not eagerly load a
    # historical class engine just to generate unrelated MC viewer snapshots.
    # The normal listener retains its legacy viewer initialization unchanged.
    if os.environ.get("WOW_DISABLE_LEGACY_DECISIONS") != "1":
        for m in sm.WATER_MODES:
            sm.publish_viewer_snapshot(m)
    else:
        print('[listener] legacy Decisions disabled: MC viewer snapshots deferred', flush=True)
    srv=ThreadingHTTPServer((a.host,a.port),Handler); url=f'http://{a.host}:{a.port}/'; open_url=url.rstrip('/')+a.open_path
    print(f'[listener] repo_root={sm.ROOT}',flush=True)
    print(f'[listener] state_root={sm.STATE}',flush=True)
    if os.environ.get("WOW_DISABLE_LEGACY_DECISIONS") != "1":
        for m in sm.WATER_MODES:
            school=_active_school(); sd=sm.school_seed_dir(m,school)
            print(f'[listener] {m} school={school} seeds={len(sm.viewer_seed_summaries(m,school))} dir={sd}',flush=True)
    print(f'[listener] {url} (open {open_url})',flush=True)
    if not a.no_browser: threading.Timer(.5,lambda:webbrowser.open(open_url)).start()
    try: srv.serve_forever(poll_interval=.5)
    except KeyboardInterrupt: pass
    finally: srv.server_close()

if __name__=='__main__': main()
