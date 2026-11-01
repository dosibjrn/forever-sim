from __future__ import annotations
import unittest
import numpy as np
from src.v2.mechanics_projection import sample_legal_builds,fit_mechanics_projection
from src.v2.latent_search import search_latent

class ProjectionTests(unittest.TestCase):
    def test_projection_shape(self):
        b=sample_legal_builds(20,80,3)
        p=fit_mechanics_projection(20,b,dims=4)
        z=p.transform_builds(b)
        self.assertEqual(z.shape,(len(b),4))
    def test_latent_search_projects_back_to_legal_candidate(self):
        b=sample_legal_builds(20,60,5)
        p=fit_mechanics_projection(20,b,dims=3)
        # Synthetic score on the mechanics coordinates: tests proposal/inversion
        # machinery without coupling this unit test to combat details.
        z=p.transform_builds(b); target=z[7]
        lookup={tuple(getattr(t,n) for n in t.__dataclass_fields__):i for i,t in enumerate(b)}
        def score(t):
            i=lookup[tuple(getattr(t,n) for n in t.__dataclass_fields__)]
            return float(np.sum((z[i]-target)**2))
        r=search_latent(b,20,score,dims=3,anchors=24,finalists=18,projection=p)
        self.assertIn(r.talents,b)
        self.assertGreaterEqual(r.exact_evaluations,1)

if __name__=='__main__': unittest.main()
