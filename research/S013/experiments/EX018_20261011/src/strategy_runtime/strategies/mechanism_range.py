"""Fixed Cartesian virtual TIME machines produce one strict-majority binary target."""
from copy import deepcopy
from itertools import product

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from .reentry_confirmed_range import ReentryConfirmedRange


class MechanismRange(ReentryConfirmedRange):
    def __init__(self, parameters):
        p=parameters.values
        if p.get('mechanism') not in ('VOTE9','VOTE27'):
            raise ValueError('explicit research voting mechanism required')
        if not p['confirmation']['enabled'] or p['bear']['acf_min'] is None:
            raise ValueError('original confirmation and finite bear ACF required')
        self._base={key:deepcopy(dict(value)) if hasattr(value,'items') else value
                    for key,value in p.items() if key!='mechanism'}
        super().__init__(ParameterSet(self._base))
        self._parameters=parameters

    def members(self):
        regime_offsets=(0.,) if self._parameters.values['mechanism']=='VOTE9' else (-.012,0.,.012)
        triples=list(product((-.033,0.,.033),(-1,0,1),regime_offsets))
        triples.remove((0.,0,0.))
        triples.insert(0,(0.,0,0.))
        members=[]
        for acf_offset,h_offset,regime_offset in triples:
            p=deepcopy(self._base)
            p['bear']['acf_min']+=acf_offset
            p['bear']['max_hold']=min(60,max(1,p['bear']['max_hold']+h_offset))
            p['regime_threshold']=min(.2,max(-.2,p['regime_threshold']+regime_offset))
            members.append(ReentryConfirmedRange(ParameterSet(p)))
        return members

    def calculate_history(self, inputs, sessions):
        histories=[member.calculate_history(inputs,sessions) for member in self.members()]
        count=len(histories)
        assert count in (9,27)
        target_matrix=np.column_stack([frame.target_position.to_numpy() for frame in histories])
        if not np.isin(target_matrix,[0.,1.]).all():
            raise ValueError('member target must be binary')
        votes=target_matrix.sum(axis=1).astype(int)
        target=votes >= count//2+1
        prior=np.r_[False,target[:-1]]
        reason=np.where(target & ~prior,'entry',np.where(target,'hold',np.where(prior,'vote','flat')))
        result=histories[0].assign(target_position=target.astype(float),signal_reason=reason,
            regime='ensemble',center_regime=histories[0].regime,
            ensemble_votes=votes,ensemble_members=count,ensemble_quorum=count//2+1,
            center_target=target_matrix[:,0],center_signal_reason=histories[0].signal_reason)
        member_columns={}
        for index,history in enumerate(histories):
            member_columns[f'member_{index}_target']=target_matrix[:,index]
            member_columns[f'member_{index}_reason']=history.signal_reason
            member_columns[f'member_{index}_regime']=history.regime
        return pd.concat([result,pd.DataFrame(member_columns,index=result.index)],axis=1)
