import json
from pathlib import Path
from itertools import product
ROOT=Path.cwd(); TMP=ROOT/'.tmp/s018_supplement'; FAMILY=ROOT/'research/S018'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
BASE=read(TMP/'base.json')
def records(n):return read(FAMILY/f'experiments/EX{n:03d}_20261104/others/results.json')['accounts']
def best(n):
 a=records(n);return max((k for k,v in a.items() if all(v['gates'].values())),key=lambda k:a[k]['candidate']['calmar'])
def summary(n):
 a=records(n); good=[(k,v) for k,v in a.items() if all(v['gates'].values())]
 print('ROUND',n,'accounts',len(a),'pass',len(good))
 for k,v in sorted(good,key=lambda kv:-kv[1]['candidate']['calmar'])[:8]:
  m=v['candidate']; print(k,{x:round(m[x],6) for x in ('calmar','annual','dd','median','coverage','october_return')},v['config'])
class Design:
 def __init__(self,n,question,center,reason):self.n=n;self.question=question;self.center=center;self.reason=reason;self.configs=[];self.add(BASE);self.add(center)
 def add(self,base=None,**changes):
  p=dict(self.center if base is None else base,**changes)
  for k in ['beta_window','entry_days','earliest_add','review_after','max_hold']:
   assert isinstance(p[k],int) and p[k]>= (2 if k=='beta_window' else 1)
  for k in ['common_budget','other_budget','initial_fraction']:assert 0<=p[k]<=1
  for k in ['exit_margin','add_mu_margin','add_sector_margin']:assert p[k]>-1
  assert p['add_mode'] in ['repair','repair_both','scheduled','weakness','never']
  if p not in self.configs:self.configs.append(p)
 def grid(self,base=None,**axes):
  for values in product(*axes.values()):self.add(base,**dict(zip(axes,values)))
 def publish(self):
  assert len(self.configs)<100
  p=dict(number=self.n,stage=3,authorization='需要端到端明确可调参数，然后做补查；原30轮剩余6轮',question=self.question,strategy_source='.tmp/s018_supplement/strategy.py',configurations=self.configs,state_fields=['anchor','sector_anchor','entry_budget'],selection_rule='原净卡玛D及五门不变；十月和尾部仅诊断',design_basis=self.reason,parameter_domains={k:sorted(set(p[k] for p in self.configs)) for k in BASE},data_scope='已批准MU/SOXX冻结数据、原预热和开发池；不使用验证样本',stop_rule='最多EX058–63六轮；不进入阶段四')
  save(TMP/f'protocol{self.n}.json',p);print('DESIGN',self.n,len(self.configs))
if __name__=='__main__':
 import sys
 summary(int(sys.argv[1]))
