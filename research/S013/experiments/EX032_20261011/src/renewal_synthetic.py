"""Synthetic renewal timing diagnostic; no market inputs or account evaluations."""
from hashlib import sha256
from importlib.metadata import version
from common import SRC,RUNS,PROTOCOLS,EXPERIMENT,context,write
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
import numpy as np

assert not (PROTOCOLS/'renewal_reference.json').exists()
rng=np.random.Generator(np.random.PCG64(13))
sample_count=100000
increments=rng.lognormal(mean=-.5*.3**2,sigma=.3,size=(sample_count,100))
progress=increments.cumsum(axis=1)
rows=[]
for horizon in (1,3,4,8,60):
    for phase in (0.,.5):
        crossed=progress+phase>=horizon
        assert crossed.any(axis=1).all()
        duration=crossed.argmax(axis=1)+1
        rows.append({'H':horizon,'fixed_phase':phase,'mean_duration':float(duration.mean()),
            'duration_bias_from_H':float(duration.mean()-horizon),
            'q10_duration':float(np.quantile(duration,.1)),'q90_duration':float(np.quantile(duration,.9))})
    for phase in (0.,.5):
        deterministic=np.arange(1,101,dtype=float)+phase>=horizon
        assert int(deterministic.argmax()+1)==horizon
result={'status':'PASS','scope':'pure synthetic independent positive increments; not market/account evidence',
    'assumptions':'iid lognormal increments, population mean1, sigma0.3, fixed seed13 and100000paths; does not model observed rolling-denominator dependence',
    'rows':rows,'constant_increment_original_integer_H_equivalence':'EXACT for both fixed phases and all tested H',
    'limits':'Toy diagnostic only; neither population duration correction nor economic/parameter benefit established on S013.'}
result['numpy_version']=version('numpy')
source=(SRC/'renewal_synthetic.py').read_bytes()
result['source']={'sha256':sha256(source).hexdigest(),'text':source.decode('utf-8')}
write(RUNS/'renewal_synthetic.json',result)
ref=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'synthetic-counting-diagnosis',
    (RUNS/'renewal_synthetic.json').read_bytes(),'application/json','json'))
write(PROTOCOLS/'renewal_reference.json',ref.to_dict())
print({'synthetic_counting_diagnosis':'PASS','new_accounts':0,'reference':ref.to_dict()})
