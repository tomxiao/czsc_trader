"""Technical loader correction only; retain frozen standalone.py unchanged."""
import standalone as s
from czsc_trader.research_tools import EvidenceRef
original=s.module
def verified_module(path,name):
    local=s.BASE/('EX036_20261023' if name=='old39' else 'EX038_20261023')/'src'/('validate.py' if name=='old39' else 'attribution.py')
    assert local.read_bytes()==path.read_bytes()
    return original(local,name)
if __name__=='__main__':
    refs=s.read(s.HERE/'others/loader_correction_refs.json')
    for filename,sub in [('run_verified.py','src'),('loader_correction.json','protocols')]:
        assert EvidenceRef.from_dict(refs[filename]).resolve(s.ROOT).read_bytes()==(s.HERE/sub/filename).read_bytes()
    s.module=verified_module
    s.run()
