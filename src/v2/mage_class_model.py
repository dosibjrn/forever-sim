from __future__ import annotations

"""Forever Mage class plugin for the shared per-level search kernel.

The mature Mage structural/policy/gear math predates ClassModel.  This adapter
keeps that implementation authoritative while moving its orchestration through
``search_level()``: Mage owns candidate generation and scoring details; the
kernel owns candidate dedup/evaluation/result assembly.
"""

from dataclasses import replace
from typing import Any, Mapping

from .class_model import EngineClassModel, Evaluation, SearchContext

MAGE_EVENT_POOL_SAMPLES = 32
MAGE_EVENT_ADJUDICATION_SAMPLES = 64


class MageClassModel(EngineClassModel):
    def runner_strategy(self) -> str:
        return "analytic_views"

    def __init__(self, engine: Any):
        super().__init__(engine)
        self._prepared: dict[Any, Any] = {}

    def apply_cli_config(self, cfg: Any, args: Any) -> Any:
        if (getattr(self.engine, "RULESET", None) == "forever"
                and bool(getattr(args, "mage_blizzard_aoe", False))):
            return replace(cfg, server_profile=cfg.server_profile.with_blizzard_aoe_leveling(True))
        return cfg

    def _node_school(self, node) -> str:
        pol=getattr(node, "policy", None)
        try:
            return self.engine.policy_primary_school(pol)
        except Exception:
            return "all"

    def rerank_repaired_pools(self, pools: Any, cfg: Any) -> Any:
        """Bounded event correction for one retained leader per Mage school.

        I14 parity rule: Frost/Arcane/Fire all enter the same event-validation
        interface. Frost Ice-Lance candidates remain additional challengers;
        event validation is no longer a Frost-only publication privilege.
        """
        if not hasattr(self.engine, "policy_search"):
            return pools
        out={}
        for level, rows0 in pools.items():
            rows=list(rows0 or ())
            if int(level) < 20 or not rows:
                out[level]=rows
                continue
            targets={}
            for school in ("frost","arcane","fire"):
                sr=[n for n in rows if self._node_school(n)==school]
                if sr:
                    n=min(sr,key=lambda x:(float(x.score_s_per_100),x.key)); targets[n.key]=(n,school)
            for n in rows:
                if int(getattr(n.talents,'ice_lance',0) or 0)>0:
                    targets[n.key]=(n,"frost")
            scored={}
            for key,(cand,school) in targets.items():
                try:
                    vr=self.engine.policy_search(int(level),cand.talents,cfg,school,n=MAGE_EVENT_POOL_SAMPLES,seed=7)
                    best=dict(vr.get('best_found') or {})
                    mph=float(best.get('mobs_per_hour') or 0.0)
                    if mph<=0: continue
                    details=dict(cand.details or {}); event_total=360000.0/mph
                    details.update({'total_s':event_total,'kill_s':100.0*float(best.get('kill_seconds_per_mob') or 0.0),'recovery_s':100.0*float(best.get('recovery_seconds_per_mob') or 0.0),'travel_s':100.0*float(best.get('travel_seconds_per_mob') or 0.0),'mean_s_per_mob':event_total/100.0})
                    details['event_structural_rerank']={'samples':MAGE_EVENT_POOL_SAMPLES,'seed':7,'mobs_per_hour':mph,'rotation':best.get('rotation'),'school':school,'timing_authority':'event'}
                    scored[key]=replace(cand,score_s_per_100=event_total,source='event_structural',details=details)
                except Exception:
                    continue
            out[level]=[scored.get(n.key,n) for n in rows]
            out[level].sort(key=lambda n:(float(n.score_s_per_100),self.build_preference_key(n.talents),n.key))
        return out

    def adjudicate_per_level_candidate(self, level: int, candidates, cfg: Any):
        node=min(candidates,key=lambda n:(float(n.score_s_per_100),n.key))
        if int(level) < 20 or not hasattr(self.engine, 'policy_search'):
            return node, {}
        challengers=[]
        for school in ("frost","arcane","fire"):
            sr=[n for n in candidates if self._node_school(n)==school]
            if sr: challengers.append((min(sr,key=lambda x:(float(x.score_s_per_100),x.key)),school))
        seen={n.key for n,_ in challengers}
        for n in candidates:
            if int(getattr(n.talents,'ice_lance',0) or 0)>0 and n.key not in seen:
                challengers.append((n,"frost")); seen.add(n.key)
        event=[]
        for cand,school in challengers:
            try:
                vr=self.engine.policy_search(int(level),cand.talents,cfg,school,n=MAGE_EVENT_ADJUDICATION_SAMPLES,seed=7)
                best=dict(vr.get('best_found') or {}); mph=float(best.get('mobs_per_hour') or 0.0)
                if mph>0: event.append((mph,cand,best,school))
            except Exception:
                pass
        if not event: return node, {}
        event.sort(key=lambda x:(-x[0],x[1].key)); mph,node,best,school=event[0]
        overrides={'mobs_per_hour':mph,'score_s_per_100':360000.0/mph,'min_per_100':6000.0/mph,'seconds_per_mob':3600.0/mph,'policy':best.get('rotation'),'rotation':best.get('rotation'),'selection_validation':{'kind':'event_structural_rerank','samples':MAGE_EVENT_ADJUDICATION_SAMPLES,'seed':7,'challenger_count':len(event),'winner_school':school,'winner_mobs_per_hour':mph}}
        for key in ('kill_seconds_per_mob','recovery_seconds_per_mob','travel_seconds_per_mob'):
            if best.get(key) is not None: overrides[key]=float(best[key])
        return node, overrides


    def prepare_level_candidates(
        self, level: int, cfg: Any, *, options: Any, beam_width: int,
        family_keep: int, final_k: int, school: str = "all",
    ) -> tuple[Any, ...]:
        profile = getattr(cfg, "server_profile", None)
        if bool(getattr(profile, "blizzard_aoe_leveling_enabled", False)):
            raise RuntimeError(
                "Mage Blizzard/AoE leveling is enabled for this server profile, "
                "but the AoE geometry/channel policy scorer is not implemented yet. "
                "Refusing to publish the single-target search as an AoE result."
            )
        from .local_search import search_level_analytic

        rows = search_level_analytic(
            int(level), cfg, options=options, beam_width=int(beam_width),
            family_keep=int(family_keep), final_k=int(final_k), school=school,
        )
        # Preserve the existing Forever all-school Ice Lance corridor behavior.
        if (self.engine.normalize_primary_school(school) == "all"
                and getattr(self.engine, "RULESET", None) == "forever"
                and int(level) >= 20):
            frost_rows = search_level_analytic(
                int(level), cfg, options=options, beam_width=max(24, int(beam_width)),
                family_keep=max(4, int(family_keep)), final_k=max(24, int(final_k)), school="frost",
            )
            merged = {self.build_key(n.talents): n for n in rows}
            added = 0
            for n in frost_rows:
                if int(getattr(n.talents, "ice_lance", 0) or 0) <= 0:
                    continue
                key = self.build_key(n.talents)
                if key not in merged:
                    merged[key] = n
                    added += 1
                if added >= 12:
                    break
            rows = sorted(
                merged.values(),
                key=lambda n: (float(n.score_s_per_100), self.build_preference_key(n.talents), self.build_key(n.talents)),
            )
        self._prepared = {self.build_key(n.talents): n for n in rows}
        return tuple(n.talents for n in rows)

    def prepared_node(self, build: Any) -> Any:
        return self._prepared[self.build_key(build)]

    def candidate_optimization_is_bundled(self) -> bool:
        return True

    def optimize_policy(self, ctx: SearchContext) -> Any:
        node = self._prepared.get(self.build_key(ctx.build))
        return node.policy if node is not None else ctx.policy

    def evaluate(self, ctx: SearchContext) -> Evaluation:
        node = self._prepared.get(self.build_key(ctx.build))
        if node is None:
            raise RuntimeError("MageClassModel candidate was not prepared by the mature structural generator")
        details = dict(node.details or {})
        details["total_s"] = float(node.score_s_per_100)
        return Evaluation.from_raw(details)

    def to_level_node(self, result, *, source: str | None = None):
        """Rehydrate shared CandidateResult into the mature runner node shape."""
        node = self.prepared_node(result.build)
        details = dict(node.details or {})
        details.update(dict(result.evaluation.diagnostics or {}))
        return replace(
            node,
            score_s_per_100=float(result.evaluation.score_s_per_100),
            policy=result.policy or node.policy,
            source=source or node.source,
            details=details,
        )
