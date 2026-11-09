"""EC35: public normalization preserves units without querying a provider."""
from copy import deepcopy
from datetime import date
import pandas as pd
import pytest
from execution_channels.pricing import ExecutionPriceBasis, ExecutionPricing
from execution_channels.errors import RuntimeContractError


class Metadata(dict):
    copies=0
    def __deepcopy__(self,memo):
        type(self).copies+=1
        return Metadata({k:deepcopy(v,memo) for k,v in self.items()})


def prices(scale=.3):
    raw=pd.DataFrame({'dt':pd.to_datetime(['2025-12-31','2026-01-02','2026-01-05']),
        'open':[10.,5.,6.],'high':[10.,5.,6.],'low':[10.,5.,6.],'close':[10.,5.,6.],
        'vol':[1000.,2000.,2000.],'amount':[10000.,10000.,12000.]})
    adjusted=raw.copy()
    adjusted[['open','high','low','close']]=adjusted[['open','high','low','close']].mul(pd.Series([scale,scale*2,scale*2]),axis=0)
    return raw,adjusted


@pytest.mark.parametrize('scale',[.3,30.],ids=['EC35-C01','EC35-C02'])
def test_normalized_units_are_scale_invariant(scale):
    raw,adjusted=prices(scale)
    contract=ExecutionPricing.from_daily(ExecutionPriceBasis.HFQ_RESEARCH,raw,adjusted,date(2025,12,31))
    result=contract.apply(raw,raw_daily=raw,adjusted_daily=adjusted)
    assert result.close.tolist()==pytest.approx([10.,10.,12.])
    assert result.vol.tolist()==pytest.approx([1000.,1000.,1000.])
    assert result.amount.tolist()==raw.amount.tolist()
    assert ExecutionPricing.from_dict(contract.to_dict())==contract


def test_EC35_C03_metadata_and_prices_are_isolated_once():
    raw,adjusted=prices()
    raw.attrs={'quality':Metadata({'sessions':['original']})}
    contract=ExecutionPricing.from_daily(ExecutionPriceBasis.HFQ_RESEARCH,raw,adjusted,date(2025,12,31))
    Metadata.copies=0
    result=contract.apply(raw,raw_daily=raw,adjusted_daily=adjusted)
    assert Metadata.copies==1
    result.loc[0,'close']=99
    result.attrs['quality']['sessions'].append('changed')
    assert raw.close.tolist()==[10.,5.,6.]
    assert raw.attrs['quality']['sessions']==['original']


@pytest.mark.parametrize('fault',['nonpositive','missing','factor','anchor'],ids=['EC35-C04','EC35-C05','EC35-C06','EC35-C07'])
def test_invalid_units_fail_before_copying_evidence(fault):
    raw,adjusted=prices(1.)
    if fault=='nonpositive':
        raw.loc[0,'close']=0.
    elif fault=='missing':
        adjusted=adjusted.iloc[:-1]
    elif fault=='factor':
        adjusted.loc[1,'open']*=2
    raw.attrs={'quality':Metadata({'source':'raw'})}
    adjusted.attrs={'quality':Metadata({'source':'hfq'})}
    contract=ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH,date(2025,12,31),2. if fault=='anchor' else 1.)
    Metadata.copies=0
    with pytest.raises(RuntimeContractError):
        contract.apply(raw,raw_daily=raw,adjusted_daily=adjusted)
    assert Metadata.copies==0
