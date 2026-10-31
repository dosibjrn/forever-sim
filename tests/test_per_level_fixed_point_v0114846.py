from src.v2.per_level_fixed_point import optimize_level_fixed_point, positive_stat_values


def test_positive_stat_values_objective_gradient():
    got=positive_stat_values({"objective_gradient":{"intellect":-2.5,"stamina":1.0,"spell_power":-4.0}})
    assert got=={"intellect":2.5,"stamina":0.0,"spell_power":4.0}


def test_fixed_point_repeats_until_gear_stops_changing():
    # G0 -> G1 -> G2, then stable. Score/weights are recomputed each time.
    scores=[]
    def score(g):
        scores.append(g)
        return {"total_s":100-int(g[1:])*5,"gear":g}
    def sw(s):
        i=int(s["gear"][1:])
        return {"objective_gradient":{"intellect":-(i+1)}}
    def select(g,w):
        i=int(g[1:])
        return f"G{min(2,i+1)}"
    r=optimize_level_fixed_point(initial_gear="G0",score_with_gear=score,stat_weights=sw,
                                 select_gear=select,gear_signature=lambda g:(g,),max_iters=4)
    assert r.converged
    assert r.iterations==3
    assert r.score["gear"]=="G2"
    assert scores==["G0","G1","G2"]


def test_fixed_point_cap_publishes_best_scored_state_not_arbitrary_last_proposal():
    scores=[]
    def score(g):
        scores.append(g); return {"total_s": {0:100,1:80,2:120}[g],"gear":g}
    r=optimize_level_fixed_point(initial_gear=0,score_with_gear=score,
        stat_weights=lambda s:{"objective_gradient":{"x":-1}},
        select_gear=lambda g,w:g+1,gear_signature=lambda g:(g,),max_iters=2)
    assert not r.converged
    assert r.score["gear"]==1
    fp=r.score["gear_fixed_point"]
    assert fp["cap_policy"]=="best_scored_objective_state"
    assert [x["score_s_per_100"] for x in fp["trace"]] == [100.0,80.0]
    assert scores==[0,1,2]

def test_fixed_point_detects_cycle_and_keeps_best_scored_state():
    def score(g): return {"total_s": {0:10.0,1:8.0,2:9.0}[g], "gear":g}
    def sw(s): return {"objective_gradient":{"x":-1.0}}
    def select(g,_v): return {0:1,1:2,2:1}[g]
    r=optimize_level_fixed_point(initial_gear=0,score_with_gear=score,stat_weights=sw,
        select_gear=select,gear_signature=lambda g:(g,),max_iters=8)
    assert r.score["gear"]==1
    assert r.score["gear_fixed_point"]["cycle_detected"] is True
