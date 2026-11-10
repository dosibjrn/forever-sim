from __future__ import annotations

"""Exact layered shortest-path DP over supplied per-level candidate pools.

Candidate generation is deliberately separate.  Given a finite pool at each
level, this module is exact: a no-respec edge exists iff the child allocation is
exactly the parent plus one legal talent point; a respec edge may jump to any
legal allocation while consuming one respec budget.
"""

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from .class_model import ClassModel, active_class_model
from .objective import level_weight_per_100


@dataclass(frozen=True)
class LevelNode:
    level:int
    talents:Any
    score_s_per_100:float
    policy:Any=None
    source:str='analytic'
    details:dict|None=None

    @property
    def key(self):
        # Compatibility property for legacy callers.  The generic DP itself
        # resolves keys through ClassModel and does not inspect the build.
        return active_class_model().build_key(self.talents)


@dataclass(frozen=True)
class PathStep:
    node:LevelNode
    kind:str              # start | point | respec
    talent_added:str|None
    respecs_used:int
    cumulative_s:float


@dataclass(frozen=True)
class PathResult:
    steps:tuple[PathStep,...]
    cumulative_s:float
    respecs_used:int
    resolved_through_level:int

    @property
    def hours(self)->float:
        return self.cumulative_s/3600.0


@dataclass
class _Cell:
    cost:float
    prev:tuple[int,int]|None   # previous (node_index,respecs)
    kind:str
    talent_added:str|None


def _added_talent(parent:Any, child:Any, model:ClassModel)->str|None:
    """Generic legality hook; DP never inspects class-specific build fields."""
    return model.legal_one_point_transition(parent, child)

def _is_paid_native_level_node(node: LevelNode, level: int) -> bool:
    """Qualify native execution receipts; do not revalidate Rust gameplay."""
    receipt = (node.details or {}).get("native_receipt")
    if node.source != "native_paid" or not isinstance(receipt, Mapping):
        return False
    actor = receipt.get("native_actor")
    return (receipt.get("status") == "measured_native_chain"
            and receipt.get("level") == level
            and isinstance(actor, Mapping)
            and actor.get("class") == "ClassWarlock"
            and actor.get("level") == level
            and receipt.get("native_world_ack") is True
            and receipt.get("paid_native_recovery") is True
            and receipt.get("targets_requested") == 100
            and receipt.get("targets_killed") == 100
            and isinstance(receipt.get("source_request_sha256"), str)
            and len(receipt["source_request_sha256"]) == 64
            and isinstance(receipt.get("engine_binary_sha256"), str)
            and len(receipt["engine_binary_sha256"]) == 64)


def _dedup_level_nodes(level:int,nodes:Sequence[LevelNode], model:ClassModel,
                       *, native_paid:bool=False)->list[LevelNode]:
    """For identical talent allocations retain the lowest node score.

    Policy is free to change between levels and carries no transition state, so
    a slower policy for the same allocation is dominated inside one analytic
    view.  Stochastic policy alternatives should be preserved before calling
    this exact path DP if they are intended as separate finalists.
    """
    best={}
    for n in nodes:
        if int(n.level)!=int(level):
            raise ValueError(f'node level mismatch: expected {level}, got {n.level}')
        points=model.build_points(n.talents)
        if native_paid:
            if not _is_paid_native_level_node(n, level):
                raise ValueError(f'level {level} node lacks a matching paid native actor/chain receipt')
            # Native preparation may bank talent points. No Python game legality
            # inference is made: the execution receipt is authoritative.
            if points < 0 or points > int(level)-9:
                raise ValueError(f'level {level} native node has impossible point count {points}')
        elif points!=int(level)-9:
            raise ValueError(f'level {level} node has {points} talent points; expected {level-9}')
        # Native measurements from different executable revisions are not
        # interchangeable, even when the talent allocations are identical.
        # Keep one best observation per (allocation, engine) so a slower but
        # compatible candidate is not discarded before path solving.
        k=model.build_key(n.talents)
        if native_paid:
            k=(k, n.details["native_receipt"]["engine_binary_sha256"])
        old=best.get(k)
        if old is None or (n.score_s_per_100,model.policy_description(n.policy,level) if n.policy else '') < (old.score_s_per_100,model.policy_description(old.policy,level) if old.policy else ''):
            best[k]=n
    return sorted(best.values(),key=lambda n:(n.score_s_per_100,model.build_preference_key(n.talents),model.build_key(n.talents)))


def solve_path_dp(pools:Mapping[int,Sequence[LevelNode]],*,max_respecs:int|None=None,
                  weights:Mapping[int,float]|None=None,start_level:int|None=None,
                  end_level:int|None=None, model:ClassModel|None=None,
                  native_paid:bool=False)->PathResult:
    if not pools:
        raise ValueError('no level pools')
    model = model or active_class_model()
    levels=sorted(int(x) for x in pools)
    lo=levels[0] if start_level is None else int(start_level)
    hi=levels[-1] if end_level is None else int(end_level)
    levels=[l for l in levels if lo<=l<=hi]
    if not levels:
        raise ValueError('no levels in requested range')
    if any(b!=a+1 for a,b in zip(levels,levels[1:])):
        raise ValueError('path DP requires contiguous level pools')
    # Native-paid observations are independently executed chains. They cannot
    # establish an unmeasured respec jump, even if both endpoint builds were
    # accepted by Rust. The historical analytical mode still defaults to two.
    if max_respecs is None:
        max_respecs = 0 if native_paid else 2
    max_respecs=max(0,int(max_respecs))
    if native_paid and max_respecs:
        raise ValueError('native paid path has no prepared respec edges; set max_respecs=0')
    pp={l:_dedup_level_nodes(l,pools[l],model,native_paid=native_paid) for l in levels}
    if any(not pp[l] for l in levels):
        raise ValueError('empty candidate pool')
    w=weights or {l:level_weight_per_100(l) for l in levels}

    # layer[(node_index,respec_count)] -> _Cell
    history=[]
    first=levels[0]
    layer={}
    for i,n in enumerate(pp[first]):
        # Any legal allocation at the first supplied level is reachable from the
        # earlier untimed prefix; exact prefix reconstruction is outside this
        # sliced DP.  For the normal 11 start, every 2-point legal build is reachable.
        layer[(i,0)]=_Cell(float(n.score_s_per_100)*float(w.get(first,0.0)),None,'start',None)
    history.append(layer)

    for li,level in enumerate(levels[1:],start=1):
        prev_level=levels[li-1]
        prev_nodes=pp[prev_level]; nodes=pp[level]
        prev_layer=history[-1]
        nxt={}

        # Fast exact no-respec edges.  Pools are small enough that O(P*C) is
        # simpler and less error-prone than reconstructing all possible parents.
        for j,child in enumerate(nodes):
            for i,parent in enumerate(prev_nodes):
                # Compare actual adjacent receipts, not every unused candidate
                # in the input pools. Different binaries can coexist as
                # alternatives but must never be joined into one native path.
                if (native_paid and
                        parent.details["native_receipt"]["engine_binary_sha256"] !=
                        child.details["native_receipt"]["engine_binary_sha256"]):
                    continue
                # Both native-paid endpoints carry actual actor/chain receipts.
                # Unchanged talents are a banked-point hold, not a respec.
                hold = (native_paid and
                        model.build_key(parent.talents) == model.build_key(child.talents))
                added = None if hold else _added_talent(parent.talents,child.talents,model)
                if not hold and added is None:
                    continue
                for r in range(max_respecs+1):
                    pc=prev_layer.get((i,r))
                    if pc is None:
                        continue
                    cost=pc.cost+float(child.score_s_per_100)*float(w.get(level,0.0))
                    key=(j,r); old=nxt.get(key)
                    if old is None or cost<old.cost-1e-12:
                        nxt[key]=_Cell(cost,(i,r),'hold' if hold else 'point',added)

        # Respec jump: because the jump cost itself is zero and the destination
        # local score depends only on the child, only the cheapest source at r-1
        # matters for each destination.
        for r in range(1,max_respecs+1):
            sources=[(cell.cost,i) for (i,rr),cell in prev_layer.items() if rr==r-1]
            if not sources:
                continue
            src_cost,src_i=min(sources)
            for j,child in enumerate(nodes):
                cost=src_cost+float(child.score_s_per_100)*float(w.get(level,0.0))
                key=(j,r); old=nxt.get(key)
                if old is None or cost<old.cost-1e-12:
                    nxt[key]=_Cell(cost,(src_i,r-1),'respec',None)
        if not nxt:
            raise ValueError(f'no legal path reaches level {level}; candidate pools lack continuity')
        history.append(nxt)

    last_layer=history[-1]
    (end_i,end_r),end_cell=min(last_layer.items(),key=lambda kv:(kv[1].cost,kv[0][1],kv[0][0]))
    rev=[]; cur=(end_i,end_r)
    for li in range(len(levels)-1,-1,-1):
        level=levels[li]; cell=history[li][cur]
        node=pp[level][cur[0]]
        rev.append(PathStep(node,cell.kind,cell.talent_added,cur[1],cell.cost))
        if cell.prev is None:
            break
        cur=cell.prev
    rev.reverse()
    return PathResult(tuple(rev),end_cell.cost,end_r,levels[-1])
