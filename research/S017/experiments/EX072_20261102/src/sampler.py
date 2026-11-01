"""One fixed six-dimensional public Optuna interface; no independent fallback."""
import optuna

KEYS=('alpha','initial_fraction','accepted_fraction','g_when_u','g_when_other','g_when_mf')
DOMAINS={k:(0.,2. if k=='alpha' else 1.) for k in KEYS}


class AuditedJointTPESampler(optuna.samplers.TPESampler):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.independent_calls=0;self.last_relative_space=[];self.relative_space_checks=0;self.model_samples=[]
    def infer_relative_search_space(self,study,trial):
        space=super().infer_relative_search_space(study,trial)
        self.last_relative_space=sorted(space);self.relative_space_checks+=1
        return space
    def sample_relative(self,study,trial,search_space):
        result=super().sample_relative(study,trial,search_space)
        if trial.number>=5:
            complete=sum(t.state is optuna.trial.TrialState.COMPLETE for t in study.get_trials(deepcopy=False))
            if complete<5 or set(search_space)!=set(KEYS) or set(result)!=set(KEYS):
                raise RuntimeError('Model requires five COMPLETE anchors and whole six-dimensional relative sampling')
            self.model_samples.append(dict(trial=trial.number,complete_before=complete,space=sorted(search_space),returned=sorted(result)))
        return result
    def sample_independent(self,study,trial,param_name,param_distribution):
        self.independent_calls+=1
        raise RuntimeError('Independent fallback forbidden; all six FloatDistributions must share the joint model')


def new_sampler():
    return AuditedJointTPESampler(seed=17,n_startup_trials=5,multivariate=True,constant_liar=True,
        constraints_func=lambda t:t.user_attrs['sampling_constraint_vector'])


def suggest(trial):
    return {k:trial.suggest_float(k,*DOMAINS[k]) for k in KEYS}
