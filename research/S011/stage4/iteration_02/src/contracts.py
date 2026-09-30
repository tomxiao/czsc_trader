"""Strict standard-library research records; no additional dependencies."""
from copy import deepcopy
from hashlib import sha256
import json
import math
import re

def require(condition,message):
    if not condition: raise ValueError(message)

def canonical(value):
    def normal(x):
        if isinstance(x,float):
            require(math.isfinite(x),'nonfinite identity')
            return 0.0 if x==0 else x
        if isinstance(x,dict):return {k:normal(v) for k,v in x.items()}
        if isinstance(x,list):return [normal(v) for v in x]
        return x
    return json.dumps(normal(value),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

class Record:
    names=set()
    defaults={}
    def __init__(self,**values):
        values={**deepcopy(self.defaults),**deepcopy(values)}
        require(set(values)==self.names,'invalid fields for '+type(self).__name__)
        self.validate(values)
        self._value=values
    def validate(self,values):pass
    def __getattr__(self,name):return self._value[name]
    def model_dump(self):return deepcopy(self._value)
    @classmethod
    def model_validate(cls,value):
        if isinstance(value,cls):return value
        require(type(value) is dict,'expected object')
        return cls(**value)
    @classmethod
    def model_json_schema(cls):return SCHEMAS[cls.__name__]

class Definition(Record):
    names={'strategy_kind','symbol','parameters','runtime'}
    def validate(self,v):
        require(v['strategy_kind']=='s011_short_pressure_reversal' and v['symbol']=='159326.SZ','strategy identity')
        p=v['parameters'];r=v['runtime']
        require(type(p) is dict and set(p)=={'tail_weight','spx_weight','entry','exit','max_days','lookback','premium'},'parameter names')
        for name in ('tail_weight','spx_weight','entry','exit','premium'):
            require(type(p[name]) in (int,float) and math.isfinite(p[name]),'finite numeric parameter')
            p[name]=float(p[name])
        require(type(p['max_days']) is int and type(p['lookback']) is int,'integer type')
        require(0<=p['tail_weight']<=1 and 0<=p['spx_weight']<=1 and -.5<=p['exit']<p['entry']<=.5 and 1<=p['max_days']<=3 and 20<=p['lookback']<=240 and 0<=p['premium']<=.01,'parameter bounds')
        require(type(r) is dict and set(r)=={'module','qualname','contract_version','source_files','source_sha256'},'runtime fields')
        require(type(r['module']) is str and type(r['qualname']) is str and type(r['contract_version']) is int,'runtime types')
        require(type(r['source_files']) is list and bool(r['source_files']),'source list')
        require(all(type(x) is str and not re.match(r'[/\\]|[A-Za-z]:',x) and '..' not in x.split('/') for x in r['source_files']),'source paths')
        require(bool(re.fullmatch('[0-9a-f]{64}',r['source_sha256'])),'source hash')

def fingerprint(payload):
    return sha256(canonical({'version':'S011_TYPED_CANONICAL_JSON_V1','definition':Definition.model_validate(payload).model_dump()}).encode()).hexdigest()

class Configuration(Record):
    names={'config_id','config_fingerprint','definition','source_root','first_reference','references','scope'}
    def validate(self,v):
        require(bool(re.fullmatch(r'S011-CFG-[0-9]{6}',v['config_id'])) and not v['config_id'].endswith('000000'),'config ID')
        v['definition']=Definition.model_validate(v['definition']).model_dump()
        require(v['config_fingerprint']==fingerprint(v['definition']),'fingerprint mismatch')
        require(v['scope'] in ('COMPARABLE_DEVELOPMENT','NONCOMPARABLE_LEGACY'),'scope')
        require(type(v['references']) is list and v['first_reference'] in v['references'] and all(type(x) is str for x in v['references']),'references')
        require(type(v['source_root']) is str and not re.match(r'[/\\]|[A-Za-z]:',v['source_root']),'relative source root')

class Registry(Record):
    names={'schema_version','strategy_id','fingerprint_version','configurations'}
    defaults={'schema_version':1,'strategy_id':'S011','fingerprint_version':'S011_TYPED_CANONICAL_JSON_V1'}
    def validate(self,v):
        require(v['schema_version']==1 and v['strategy_id']=='S011' and v['fingerprint_version']=='S011_TYPED_CANONICAL_JSON_V1','registry version')
        v['configurations']=[Configuration.model_validate(c).model_dump() for c in v['configurations']]
        for key in ('config_id','config_fingerprint'):
            vals=[c[key] for c in v['configurations']]
            require(len(vals)==len(set(vals)),'duplicate '+key)

class Pareto(Record):
    names={'schema_version','metrics','layers','dominated_by','unranked','automatic_promotion'}
    defaults={'schema_version':1,'automatic_promotion':False}
    def validate(self,v):
        require(v['schema_version']==1 and v['automatic_promotion'] is False,'no automatic promotion')
        for m in v['metrics']:
            require(set(m)=={'name','direction','decimals'} and m['direction'] in ('maximize','minimize') and type(m['decimals']) is int and 0<=m['decimals']<=14,'metric contract')
        seen=[]
        for i,layer in enumerate(v['layers']):
            require(set(layer)=={'layer','config_ids'} and layer['layer']==i+1,'layer contract')
            seen.extend(layer['config_ids'])
        require(len(seen)==len(set(seen)) and not set(seen)&set(v['unranked']),'ranking identity')

class Decision(Record):
    names={'schema_version','status','selected_config_ids','user_approval','stage_five_started'}
    defaults={'schema_version':1,'status':'PENDING_USER_DECISION','selected_config_ids':[],'user_approval':None,'stage_five_started':False}
    def validate(self,v):
        require(v==self.defaults,'explicit user approval required; research build only creates pending decisions')

def pareto_layers(rows,metrics):
    require(len(rows)==len({r['config_id'] for r in rows}),'duplicate ranking identity')
    signs=[1 if m['direction']=='maximize' else -1 for m in metrics]
    vectors={};unranked={}
    for row in rows:
        values=[row.get(m['name']) for m in metrics]
        if not all(type(x) in (int,float) and math.isfinite(x) for x in values):
            unranked[row['config_id']]='MISSING_OR_NONFINITE_COMPARISON_METRIC';continue
        vectors[row['config_id']]=[s*round(x,m['decimals']) for x,m,s in zip(values,metrics,signs)]
    dominated={x:[] for x in vectors}
    for x,a in vectors.items():
        for y,b in vectors.items():
            if x!=y and all(v>=u for v,u in zip(b,a)) and any(v>u for v,u in zip(b,a)):dominated[x].append(y)
    remaining=set(vectors);layers=[]
    while remaining:
        front=sorted(x for x in remaining if not (set(dominated[x])&remaining))
        require(bool(front),'dominance cycle')
        layers.append({'layer':len(layers)+1,'config_ids':front});remaining-=set(front)
    return Pareto(metrics=metrics,layers=layers,dominated_by=dominated,unranked=unranked).model_dump()

def object_schema(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def document_schema(value):
    """Schema for a versioned result document; not a universal inference engine."""
    if value is None:return {'type':'null'}
    if type(value) is bool:return {'type':'boolean'}
    if type(value) is int:return {'type':'integer'}
    if type(value) is float:return {'type':'number'}
    if type(value) is str:return {'type':'string'}
    if type(value) is dict:return object_schema({k:document_schema(v) for k,v in value.items()})
    if type(value) is list:
        alternatives={canonical(document_schema(v)):document_schema(v) for v in value}
        if not alternatives:return {'type':'array','maxItems':0}
        items=list(alternatives.values())
        return {'type':'array','items':items[0] if len(items)==1 else {'anyOf':items}}
    raise TypeError('unsupported JSON document value')


def validate_document(value,schema):
    """Validate precisely the JSON Schema subset emitted by this research package."""
    if 'anyOf' in schema:
        for option in schema['anyOf']:
            try:validate_document(value,option);return
            except ValueError:pass
        raise ValueError('no schema alternative matches')
    if 'const' in schema:require(type(value) is type(schema['const']) and value==schema['const'],'constant')
    if 'enum' in schema:require(value in schema['enum'],'enum')
    kind=schema.get('type')
    types={'null':(type(None),),'boolean':(bool,),'integer':(int,),'number':(int,float),'string':(str,),'array':(list,),'object':(dict,)}
    if kind:require(type(value) in types[kind],'JSON type '+kind)
    if kind in ('number','integer'):
        require(math.isfinite(value),'finite number')
        if 'minimum' in schema:require(value>=schema['minimum'],'minimum')
        if 'maximum' in schema:require(value<=schema['maximum'],'maximum')
    if kind=='string' and 'pattern' in schema:require(bool(re.search(schema['pattern'],value)),'pattern')
    if kind=='array':
        if 'maxItems' in schema:require(len(value)<=schema['maxItems'],'array length')
        for item in value:validate_document(item,schema.get('items',{}))
    if kind=='object':
        require(set(schema.get('required',[]))<=set(value),'required fields')
        properties=schema.get('properties',{})
        for key,item in value.items():
            if key in properties:validate_document(item,properties[key])
            else:
                extra=schema.get('additionalProperties',True)
                require(extra is not False,'unexpected field '+key)
                if type(extra) is dict:validate_document(item,extra)

S={'type':'string'};N={'type':'number'};A={'type':'array','items':S}
PARAM=object_schema({**{k:N for k in ('tail_weight','spx_weight','entry','exit','premium')},'max_days':{'type':'integer','minimum':1,'maximum':3},'lookback':{'type':'integer','minimum':20,'maximum':240}})
RUNTIME=object_schema({'module':S,'qualname':S,'contract_version':{'type':'integer'},'source_files':A,'source_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'}})
DEF=object_schema({'strategy_kind':{'const':'s011_short_pressure_reversal'},'symbol':{'const':'159326.SZ'},'parameters':PARAM,'runtime':RUNTIME})
CFG=object_schema({'config_id':{'type':'string','pattern':'^S011-CFG-[0-9]{6}$'},'config_fingerprint':{'type':'string','pattern':'^[0-9a-f]{64}$'},'definition':DEF,'source_root':S,'first_reference':S,'references':A,'scope':{'enum':['COMPARABLE_DEVELOPMENT','NONCOMPARABLE_LEGACY']}})
SCHEMAS={'Registry':object_schema({'schema_version':{'const':1},'strategy_id':{'const':'S011'},'fingerprint_version':{'const':'S011_TYPED_CANONICAL_JSON_V1'},'configurations':{'type':'array','items':CFG}}),
'Decision':object_schema({'schema_version':{'const':1},'status':{'const':'PENDING_USER_DECISION'},'selected_config_ids':{'type':'array','maxItems':0},'user_approval':{'type':'null'},'stage_five_started':{'const':False}}),
'Pareto':object_schema({'schema_version':{'const':1},'metrics':{'type':'array','items':object_schema({'name':S,'direction':{'enum':['maximize','minimize']},'decimals':{'type':'integer'}})},'layers':{'type':'array','items':object_schema({'layer':{'type':'integer'},'config_ids':A})},'dominated_by':{'type':'object','additionalProperties':A},'unranked':{'type':'object','additionalProperties':S},'automatic_promotion':{'const':False}})}
