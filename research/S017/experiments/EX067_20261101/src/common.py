"""EX067 public authentication/publication; deliberately no account-evaluation API."""
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
WORK=Path(__file__).resolve().parents[1]
SCRATCH=ROOT/'.tmp/s017_ex067_runtime'
SCRATCH.mkdir(parents=True,exist_ok=True)
os.environ['TEMP']=os.environ['TMP']=str(SCRATCH)
sys.dont_write_bytecode=True
from dataflows import ProviderConfig,BarFrequency
from strategy_runtime import ResearchExecutionSpec,UsEquitySpec,AccountPolicy,CashAvailabilityPolicy,ExecutionResources
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite
from czsc_trader.research_tools.equity_replay import materialize_equity

FIELDS={'decisions':('observed_through','decision_at','execution_start','execution_end','target','reference_price','limit_price','quantity','side','signal_status'),
 'orders':('valid_start','valid_end','side','quantity','limit_price','status','reason'),
 'fills':('interval_start','interval_end','side','quantity','price','fees','time_precision'),
 'account_points':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),
 'account_daily':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),
 'trades':('entry_at','exit_at','cost','income','net_pnl','net_return','status')}

def read(path):return json.loads(path.read_bytes())
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def checked(ref):
    ref=EvidenceRef.from_dict(ref);assert ref.experiment.strategy_id=='S017'
    p=ref.resolve(ROOT);assert digest(p)==ref.sha256
    return p,ref
def auth(record):
    p,ref=checked(record['evidence']);raw=p.read_bytes();env=json.loads(raw)
    allowed={(env[k]['kind'],env[k]['sha256']) for k in ('input_ref','candidate_ref','benchmark_ref')};deps={}
    def resolver(item):
        assert (item['kind'],item['sha256']) in allowed
        path=p.parent/(item['sha256']+'.json');assert digest(path)==item['sha256']
        deps[item['sha256']]={'kind':item['kind'],'path':path.relative_to(ROOT).as_posix()}
        return path.read_bytes()
    payload=materialize_equity(raw,resolver).payload
    for field in ('evaluation_identity','evaluation_id','request_hash'):assert payload[field]==record[field]
    inputs=json.loads(resolver(env['input_ref']))
    return payload,inputs,{'record':record,'dependencies':deps,'envelope_sha256':ref.sha256}
def projection(run):return {table:[{k:r[k] for k in keys} for r in run[table]] for table,keys in FIELDS.items()}
def context():
    spec=ResearchExecutionSpec(UsEquitySpec(),BarFrequency.M30,AccountPolicy('USD',CashAvailabilityPolicy.IMMEDIATE_RESEARCH),1,.01,.01,0.)
    return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S017'),providers=ProviderConfig(bindings={},equity_bindings={}),execution_spec=spec,resources=ExecutionResources(1,1,17))
def material(path):
    media={'.json':'application/json','.md':'text/markdown','.py':'text/x-python'}[path.suffix]
    name=path.relative_to(WORK).as_posix().replace('/','-')
    return publish_evidence(context(),MaterialEvidenceWrite(ExperimentRef('S017',WORK.name),name,path.read_bytes(),media,path.suffix[1:])).to_dict()
