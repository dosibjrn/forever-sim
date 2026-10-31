import unittest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.analytic_frontier import default_views
from src.v2.local_search import search_level_analytic
from src.v2.continuity import close_pools_forward
from src.v2.path_dp import solve_path_dp

class ContinuityGuaranteeTests(unittest.TestCase):
    def test_zero_respec_path_survives_independent_pools(self):
        cfg=eng.SimConfig()
        view=default_views()[0]
        pools={l:search_level_analytic(l,cfg,options=view.options,beam_width=5,family_keep=1,final_k=3)
               for l in range(11,18)}
        repaired=close_pools_forward(pools,cfg,view,parent_k=1,start_level=11,end_level=17,max_workers=1)
        p=solve_path_dp(repaired,max_respecs=0,start_level=11,end_level=17)
        self.assertEqual(p.resolved_through_level,17)
        self.assertEqual(p.respecs_used,0)
        self.assertEqual(len(p.steps),7)
        for a,b in zip(p.steps,p.steps[1:]):
            self.assertEqual(b.node.talents.points(),a.node.talents.points()+1)

if __name__=='__main__': unittest.main()
