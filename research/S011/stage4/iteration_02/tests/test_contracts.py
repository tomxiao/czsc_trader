from pathlib import Path
import sys
import unittest
import copy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from contracts import Definition,Configuration,Registry,Decision,fingerprint,pareto_layers,document_schema,validate_document
from analytics import bootstrap_job
from verify import independent_sharpes
from inputs import evidence_digest_bytes
import numpy as np

PAYLOAD={'strategy_kind':'s011_short_pressure_reversal','symbol':'159326.SZ',
    'parameters':{'tail_weight':.575,'spx_weight':.05,'entry':.325,'exit':.025,'max_days':2,'lookback':130,'premium':.0025},
    'runtime':{'module':'strategy_runtime.strategies.s011_reversal','qualname':'S011Reversal','contract_version':1,'source_files':['strategies/s011_reversal.py'],'source_sha256':'a'*64}}


class ContractTests(unittest.TestCase):
    def test_fingerprint_order_and_negative_zero(self):
        a=copy.deepcopy(PAYLOAD);b=copy.deepcopy(a);a['parameters']['exit']=0.;b['parameters']['exit']=-0.
        self.assertEqual(fingerprint(a),fingerprint(dict(reversed(list(b.items())))))
    def test_runtime_version_creates_new_identity(self):
        b=copy.deepcopy(PAYLOAD);b['runtime']['source_sha256']='b'*64
        self.assertNotEqual(fingerprint(PAYLOAD),fingerprint(b))
    def test_parameter_change_creates_new_identity(self):
        b=copy.deepcopy(PAYLOAD);b['parameters']['premium']=.003
        self.assertNotEqual(fingerprint(PAYLOAD),fingerprint(b))
    def test_invalid_parameters(self):
        for key,value in [('max_days',2.),('max_days',True),('tail_weight',float('nan')),('exit',.4),('lookback',241),('premium',-.01)]:
            with self.subTest(key=key,value=value):
                p=copy.deepcopy(PAYLOAD);p['parameters'][key]=value
                with self.assertRaises(ValueError):Definition.model_validate(p)
    def test_unknown_fields_rejected(self):
        p=copy.deepcopy(PAYLOAD);p['mystery']=1
        with self.assertRaises(ValueError):Definition.model_validate(p)
    def test_id_and_duplicate_registry(self):
        c={'config_id':'S011-CFG-000001','config_fingerprint':fingerprint(PAYLOAD),'definition':PAYLOAD,
            'source_root':'experiments/S011/runtime','first_reference':'EX27T000','references':['EX27T000'],'scope':'COMPARABLE_DEVELOPMENT'}
        Configuration(**c)
        with self.assertRaises(ValueError):Registry(configurations=[c,c])
        with self.assertRaises(ValueError):Configuration(**{**c,'config_id':'S011-CFG-000000'})
        with self.assertRaises(ValueError):Configuration(**{**c,'config_fingerprint':'0'*64})
    def test_no_auto_promotion(self):
        Decision()
        with self.assertRaises(ValueError):Decision(selected_config_ids=['S011-CFG-000001'])
        with self.assertRaises(ValueError):Decision(status='APPROVED')
    def test_document_schema_types_and_extra_fields(self):
        value={'a':1,'b':[{'x':True},{'y':None}]};schema=document_schema(value)
        validate_document(value,schema)
        with self.assertRaises(ValueError):validate_document({**value,'extra':1},schema)
        with self.assertRaises(ValueError):validate_document({**value,'a':True},schema)
    def test_local_zero_return_blocks(self):
        values=independent_sharpes(np.array([[0.,.01,.01],[0.,.01,-.01],[0.,.01,.02]]))
        self.assertEqual(values[0],0.)
        self.assertTrue(np.isnan(values[1]))
        self.assertTrue(np.isfinite(values[2]))
    def test_hash_policy_preserves_experiment_bytes(self):
        self.assertEqual(evidence_digest_bytes('research/x.json',b'a\r\n'),evidence_digest_bytes('research/x.json',b'a\n'))
        self.assertNotEqual(evidence_digest_bytes('experiments/x.json',b'a\r\n'),evidence_digest_bytes('experiments/x.json',b'a\n'))
        self.assertNotEqual(evidence_digest_bytes('research/x.parquet',b'a\r\n'),evidence_digest_bytes('research/x.parquet',b'a\n'))
    def test_layers_tradeoffs_ties_missing(self):
        metrics=[{'name':'gain','direction':'maximize','decimals':8},{'name':'risk','direction':'minimize','decimals':8}]
        rows=[{'config_id':c,'gain':g,'risk':r} for c,g,r in [('A',2.,2.),('B',1.,1.),('C',1.,2.),('D',1.,2.),('E',None,1.)]]
        result=pareto_layers(rows,metrics)
        self.assertEqual(result['layers'],[{'layer':1,'config_ids':['A','B']},{'layer':2,'config_ids':['C','D']}])
        self.assertEqual(set(result['unranked']),{'E'})
        self.assertFalse(result['automatic_promotion'])
    def test_constant_equal_and_empty(self):
        m=[{'name':'x','direction':'maximize','decimals':8}]
        self.assertEqual(pareto_layers([],m)['layers'],[])
        self.assertEqual(len(pareto_layers([{'config_id':'A','x':1.},{'config_id':'B','x':1.+1e-12}],m)['layers']),1)
    def test_bootstrap_reproducible_and_zero_excess(self):
        r=np.array([.01,-.02,.02,0.]*8)
        task=('A',r,r,{'seed':1,'blocks':[2,4],'repetitions':30})
        self.assertEqual(bootstrap_job(task),bootstrap_job(task))
        for row in bootstrap_job(task):self.assertEqual((row['lower'],row['median'],row['upper'],row['positive_share']),(0.,0.,0.,0.))


if __name__=='__main__':unittest.main()
