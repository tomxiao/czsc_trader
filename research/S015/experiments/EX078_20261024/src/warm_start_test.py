"""Verify public ask/tell initializes sampler constraints using actual old results."""
from pathlib import Path
import importlib.util,json
import optuna
H=Path(__file__).resolve().parents[1]
def main():
 spec=importlib.util.spec_from_file_location('corrected_search',H/'src/search.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 rows=m.read(H.parent/'EX076_20261024/others/results.json')['rows']
 study=optuna.create_study(directions=['maximize','minimize','maximize','minimize'],sampler=optuna.samplers.TPESampler(seed=13,constraints_func=lambda t:t.user_attrs['constraint_violations']))
 for r in rows:
  study.enqueue_trial(r['parameters']);t=study.ask();t.suggest_categorical('center_kind',['mean','median']);t.suggest_int('lookback',2,10);t.suggest_float('allocation',.6,1.,step=.025);t.suggest_float('minimum_repair_space',0.,.02)
  t.set_user_attr('constraint_violations',m.constraints(r));study.tell(t,m.values(r));assert list(study.get_trials()[-1].system_attrs['constraints'])==m.constraints(r)
 out={'status':'PASS','rows':len(rows),'new_accounts':0,'public_after_trial_constraints_present':True,'optuna_version':optuna.__version__}
 (H/'others/warm_start_unit_check.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8');print(out,flush=True)
if __name__=='__main__':main()
