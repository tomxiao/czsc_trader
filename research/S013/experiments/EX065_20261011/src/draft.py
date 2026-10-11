"""Fixed two-policy, original13 geometry; no data/account/provider operations."""
from dataclasses import dataclass, replace
from pathlib import Path
import importlib.util
import sys
from strategy_manager import CandidateKey
from strategy_runtime import StrategyCandidate, implementation_sha256
from strategy_evaluator import (AssessmentCandidate, ParameterCoordinate,
    ParameterCoordinateKind, ParameterDesignRequest, ParameterSpace,
    build_parameter_perturbation_design)

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
ORIGINAL = 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY'
GAP = ORIGINAL+'_GAP_REPAIR_EXIT'
PROTOTYPE = ROOT/'.tmp/s013-gap-exit-prototype/strategy_runtime'

def base():
    name = '_gap_original_geometry'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT/'.tmp/s013-management-driver/draft.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]

GATES = ('return','annual_drawdown','frequency','negative_buyhold_year_profit')
PROTOCOL = base().PROTOCOL
plain = base().plain
metadata = base().metadata
get = base().get
materialize = base().materialize
pairing_status = base().pairing_status
summarize = base().summarize
pressure_request = base().pressure_request

@dataclass(frozen=True, slots=True)
class Reservation:
    experiment_id: str
    center: str
    points: tuple[str, ...]

    def __post_init__(self):
        if not self.experiment_id or any(c in self.experiment_id for c in '/\\:'):
            raise ValueError('Explicit safe experiment ID required')
        if len(self.points)!=32 or len(set((self.center,*self.points)))!=33 or 'C8880' in (self.center,*self.points):
            raise ValueError('33 independent new IDs required')
        for identifier in (self.center,*self.points):
            CandidateKey('S013',identifier)

def candidate(label, identifier, parameters):
    CandidateKey('S013',identifier)
    if label=='B0':
        return base().candidate('B0',identifier,parameters)
    if label!='N_GAP_EXIT':
        raise ValueError('Only fixed B0/N_GAP_EXIT')
    p = plain(parameters)
    p['mechanism']=GAP
    if p['exit_on_regime_change'] is not True:
        raise ValueError('All original regime exits remain active')
    files=['strategies/'+path.name for path in sorted((PROTOTYPE/'strategies').glob('*.py'))]
    if len(files)!=7 or 'strategies/gap_repair_exit_range.py' not in files:
        raise ValueError('Exact seven-file source closure required')
    return StrategyCandidate('S013',identifier,{'parameters':p,'runtime':{
        'contract_version':1,'module':'strategy_runtime.strategies.gap_repair_exit_range',
        'qualname':'GapRepairExitRange','source_files':files,
        'source_sha256':implementation_sha256(files,source_root=PROTOTYPE)}},PROTOTYPE)

def parameter_draft(label, request, gates, identifiers, *, content_sha256, mapping_sha256, feasibility_sha256):
    if label!='N_GAP_EXIT' or set(gates)!=set(GATES) or any(type(v) is not bool for v in gates.values()):
        raise ValueError('Fixed new center and allfour bool gates required')
    if not all(gates.values()):
        return {'status':'NOT_APPLICABLE','children':(),'new_account_preparations':0}
    Reservation(request.experiment_id,request.strategy.candidate_id,tuple(identifiers))
    p=plain(request.strategy.payload['parameters'])
    if p['mechanism']!=GAP or p['exit_on_regime_change'] is not True:
        raise ValueError('Original source/entry/exit contract changed')
    _,coordinates=metadata()
    space=ParameterSpace(tuple(ParameterCoordinate(name,float(get(p,name)),lo,hi,
        ParameterCoordinateKind(kind)) for name,lo,hi,kind in coordinates),mapping_sha256,feasibility_sha256)
    design=build_parameter_perturbation_design(ParameterDesignRequest(
        AssessmentCandidate(request.strategy.reference_id,content_sha256),PROTOCOL,space),
        feasibility=lambda v:bool(v[1]<v[2] and v[5]<v[6]))
    if design.status.value!='COMPLETE' or len(design.design.points)!=32:
        raise ValueError('Prescribed geometry incomplete, no alternate seed')
    children=[]
    for identifier,point in zip(identifiers,design.design.points,strict=True):
        child=candidate(label,identifier,materialize(p,coordinates,point.coordinates))
        children.append(replace(request,strategy=child,runtime_binding={
            'candidate_id':child.reference_id,'source_files':list(child.payload['runtime']['source_files']),
            'implementation_sha256':child.payload['runtime']['source_sha256']},
            execution_data=None,input_bindings={},lineage=None))
    return {'status':'UNPREPARED_PARAMETER_BLUEPRINT','design':design.design,
        'children':tuple(children),'new_account_preparations':0}

@dataclass(frozen=True, slots=True)
class Summary:
    label: str
    gates: tuple[bool,bool,bool,bool]
    center_cagr: float
    center_drawdown: float
    q10_cagr: float|None
    q90_drawdown: float|None
    joint_pass_count: int|None

    def __post_init__(self):
        proxy=base().Summary('B0' if self.label=='B0' else 'N_LOCK',self.gates,
            self.center_cagr,self.center_drawdown,self.q10_cagr,self.q90_drawdown,self.joint_pass_count)
        if self.label not in ('B0','N_GAP_EXIT') or proxy is None:
            raise ValueError('Fixed labels required')

def selection(rows):
    if len(rows)!=2 or {r.label for r in rows}!={'B0','N_GAP_EXIT'}:
        raise ValueError('Both rows required')
    b,n=(next(r for r in rows if r.label==label) for label in ('B0','N_GAP_EXIT'))
    qualified=all(n.gates)
    absolute=qualified and n.q10_cagr>=b.q10_cagr and n.q90_drawdown<=b.q90_drawdown and (n.q10_cagr>b.q10_cagr or n.q90_drawdown<b.q90_drawdown)
    return {'preferred':'N_GAP_EXIT' if absolute else None,
        'fivecheck_labels':['B0']+(['N_GAP_EXIT'] if qualified else []),
        'absolute_tail_improvement':absolute,'center_qualification_unchanged':True,
        'four_tail_nonworsening':bool(absolute and max(0,n.center_cagr-n.q10_cagr)<=max(0,b.center_cagr-b.q10_cagr) and max(0,n.q90_drawdown-n.center_drawdown)<=max(0,b.q90_drawdown-b.center_drawdown))}
