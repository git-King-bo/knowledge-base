import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
from app.services.talent_search_index import _load, person_scores


class TalentIndexTests(unittest.TestCase):
    def test_person_aggregation_and_authorization(self):
        index=(['allowed','private','allowed'],np.array([[.6,.8],[1,0],[.8,.6]]))
        self.assertEqual(set(person_scores(index,[1,0],{'allowed'})),{'allowed'})
        self.assertAlmostEqual(person_scores(index,[1,0],{'allowed'})['allowed'],.8)
        for vector in ([1], [0,0], [float('nan'),0]):
            with self.assertRaises(ValueError):person_scores(index,vector,{'allowed'})

    def test_complete_artifact_and_corruption_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'index.npz'
            np.savez(path,ids=np.array(['a','b']),matrix=np.array([[3,4],[0,2]]))
            with patch('app.services.talent_search_index.Session') as session:
                session.return_value.__enter__.return_value.execute.return_value.all.return_value=[]
                ids,matrix=_load(Mock(),['source'],'model',path,{'a','b'})
                session.assert_not_called()
                self.assertEqual(ids,['a','b'])
                np.testing.assert_allclose(np.linalg.norm(matrix,axis=1),[1,1])
                # A partial/different authorization set cannot use this artifact.
                self.assertEqual(_load(Mock(),['source'],'model',path,{'a'})[0],[])
                path.write_bytes(b'broken')
                self.assertEqual(_load(Mock(),['source'],'model',path,{'a','b'})[0],[])
