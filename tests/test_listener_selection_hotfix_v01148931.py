from __future__ import annotations

import json
import shutil
import subprocess

from src import listener


def _function_line(name: str) -> str:
    prefix = f"function {name}("
    for line in listener.DECISIONS_HTML.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line
    raise AssertionError(f"missing JS function {name}")


def _run_node(source: str) -> dict:
    node = shutil.which("node")
    assert node, "node is required for bounded listener JS contract tests"
    proc = subprocess.run([node, "-e", source], capture_output=True, text=True, check=True, timeout=5)
    return json.loads(proc.stdout.strip())


def test_per_level_only_publication_populates_druid_target_route_and_latest_level():
    js = "\n".join(
        [
            _function_line("hasStatWeights"),
            _function_line("routesFor"),
            _function_line("targetsFor"),
            _function_line("syncState"),
        ]
    )
    source = f"""
let data={{
  class_metadata:{{druid:{{declared_routes:['balance'],display_name:'Druid'}}}},
  endpoint_paths:{{druid:{{targets:{{}}}}}},
  spec_matrix:{{druid:{{matrices:{{}}}}}},
  route_rows:{{druid:{{}}}},
  per_level_rows:{{druid:Array.from({{length:20}},(_,i)=>({{level:i+11,stat_weights:{{stats:{{intellect:{{status:'measured',seconds_saved_per_100_per_point:1}}}}}}}}))}}
}};
let state={{cls:'druid',target:'',route:'',level:NaN}};
const elements={{classPick:{{}},targetPick:{{}},routePick:{{}},levelPick:{{}},currentLevel:{{}},continueTarget:{{}}}};
const $=id=>elements[id];
const localStorage={{setItem(){{}}}};
function classes(){{return ['druid']}}
function classMeta(cls){{return data.class_metadata[cls]||{{}}}}
function classLabel(cls){{return 'Druid'}}
function targetMeta(cls,target){{return data?.endpoint_paths?.[cls]?.targets?.[String(target)]||{{}}}}
function matrixFor(){{return null}}
function routeLabel(cls,route){{return route}}
function setOptions(el,items,value){{el.items=items;el.value=value}}
{js}
syncState();
console.log(JSON.stringify({{
 target:state.target,route:state.route,level:state.level,
 targetValues:elements.targetPick.items.map(x=>String(x.value)),
 routeValues:elements.routePick.items.map(x=>x.value),
 levelValues:elements.levelPick.items.map(x=>Number(x.value)),
}}));
"""
    out = _run_node(source)
    assert out["target"] == "30"
    assert out["route"] == "per_level_best"
    assert out["level"] == 30
    assert out["targetValues"] == ["30"]
    assert out["routeValues"] == ["per_level_best"]
    assert out["levelValues"][0] == 11
    assert out["levelValues"][-1] == 30


def test_class_switch_resets_stale_selection_before_sync():
    html = listener.DECISIONS_HTML
    assert "state.cls=e.target.value;state.target='';state.route='';state.level=NaN;syncState({allowEmptyClass:true})" in html
    assert "state.target=e.target.value;state.route='';state.level=NaN;syncState()" in html
    assert "state.route=e.target.value;state.level=NaN;syncState()" in html
    assert "state.target=String(ts.at(-1)??'')" in html
    assert "state.level=levels.at(-1)" in html


def test_ice_lance_control_is_hidden_for_non_mage_and_restored_for_mage():
    fn = _function_line("syncClassSpecificControls")
    source = f"""
let state={{cls:'druid'}};
const elements={{validateIceLance:{{style:{{}},disabled:false}},iceLanceValidationPanel:{{style:{{display:'block'}}}},iceLanceValidation:{{innerHTML:'old'}}}};
const $=id=>elements[id];
{fn}
syncClassSpecificControls();
const druid={{display:elements.validateIceLance.style.display,disabled:elements.validateIceLance.disabled,panel:elements.iceLanceValidationPanel.style.display,content:elements.iceLanceValidation.innerHTML}};
state.cls='mage'; syncClassSpecificControls();
const mage={{display:elements.validateIceLance.style.display,disabled:elements.validateIceLance.disabled}};
console.log(JSON.stringify({{druid,mage}}));
"""
    out = _run_node(source)
    assert out["druid"] == {"display": "none", "disabled": True, "panel": "none", "content": ""}
    assert out["mage"] == {"display": "", "disabled": False}


def test_compare_to_build_remains_available_in_listener_surface():
    html = listener.DECISIONS_HTML
    assert 'id="referencePanel"' in html
    assert 'id="compareBuildUrl"' in html
    assert 'Compare to build' in html


def test_initial_load_falls_forward_to_a_class_with_current_targets_instead_of_blank_controls():
    js = "\n".join(
        [
            _function_line("hasStatWeights"),
            _function_line("routesFor"),
            _function_line("targetsFor"),
            _function_line("syncState"),
        ]
    )
    source = f"""
let data={{
  class_metadata:{{paladin:{{declared_routes:['retribution'],display_name:'Paladin'}},druid:{{declared_routes:['balance'],display_name:'Druid'}}}},
  endpoint_paths:{{paladin:{{targets:{{}}}},druid:{{targets:{{}}}}}},
  spec_matrix:{{paladin:{{matrices:{{}}}},druid:{{matrices:{{}}}}}},
  route_rows:{{paladin:{{}},druid:{{}}}},
  per_level_rows:{{paladin:[],druid:Array.from({{length:20}},(_,i)=>({{level:i+11,stat_weights:{{stats:{{intellect:{{status:'measured',seconds_saved_per_100_per_point:1}}}}}}}}))}}
}};
let state={{cls:'paladin',target:'20',route:'unconstrained',level:20}};
const elements={{classPick:{{}},targetPick:{{}},routePick:{{}},levelPick:{{}},currentLevel:{{}},continueTarget:{{}}}};
const $=id=>elements[id];
const localStorage={{setItem(){{}}}};
function classes(){{return ['paladin','druid']}}
function classMeta(cls){{return data.class_metadata[cls]||{{}}}}
function classLabel(cls){{return data.class_metadata[cls]?.display_name||cls}}
function targetMeta(cls,target){{return data?.endpoint_paths?.[cls]?.targets?.[String(target)]||{{}}}}
function matrixFor(){{return null}}
function routeLabel(cls,route){{return route}}
function setOptions(el,items,value){{el.items=items;el.value=value}}
{js}
syncState();
console.log(JSON.stringify({{
 cls:state.cls,target:state.target,route:state.route,level:state.level,
 targetCount:elements.targetPick.items.length,routeCount:elements.routePick.items.length,levelCount:elements.levelPick.items.length,
}}));
"""
    out = _run_node(source)
    assert out == {"cls": "druid", "target": "30", "route": "per_level_best", "level": 30, "targetCount": 1, "routeCount": 1, "levelCount": 20}
