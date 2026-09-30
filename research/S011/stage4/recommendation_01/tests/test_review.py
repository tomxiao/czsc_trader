from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from build import calculate,check_decision,IDS

class ReviewTests(unittest.TestCase):
    def test_all_four_preserved_without_total_order(self):
        r=calculate();self.assertEqual([x['config_id'] for x in r['items']],IDS)
        self.assertIsNone(r['global_total_order']);self.assertFalse(r['automatic_promotion'])
    def test_counterevidence_and_no_approval(self):
        for item in calculate()['items']:
            self.assertTrue(item['counterevidence']);self.assertFalse(item['approved'])
    def test_user_decision_cannot_be_inferred(self):
        with self.assertRaises(AssertionError):check_decision({'status':'APPROVED'})

if __name__=='__main__':unittest.main()
