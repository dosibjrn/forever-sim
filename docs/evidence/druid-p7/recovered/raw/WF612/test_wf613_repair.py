import unittest, random, copy
from wf613_repair import repair_proposals,best_paid
class TestRepair(unittest.TestCase):
    def setUp(self):
        self.p={'gear_ids':[1,2], 'talents':'t0','policy_spec':{'a':0}}
        self.ops=(lambda v,r: [v[0]+1,v[1]],lambda v,r:v+'x',lambda v,r:{'a':v['a']+1})
    def test_parent_unchanged_and_legal(self):
        orig=copy.deepcopy(self.p)
        ps=repair_proposals(self.p,random.Random(2),*self.ops,lambda c:True)
        self.assertEqual(self.p,orig)
        self.assertTrue(ps)
        self.assertTrue(all(x!=orig for x in ps))
    def test_fail_closed(self):
        self.assertEqual(repair_proposals(self.p,random.Random(2),*self.ops,lambda c:False),[])
    def test_paid_budget(self):
        calls=[]
        b,n=best_paid([1,2,3],lambda x:(calls.append(x) or x),lambda:2-len(calls))
        self.assertEqual((b,n),((2,2),2))
    def test_invalid_width(self):
        with self.assertRaises(ValueError):repair_proposals(self.p,random.Random(1),*self.ops,lambda x:True,width=0)
if __name__=='__main__': unittest.main()
