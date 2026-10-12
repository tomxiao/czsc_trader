"""Explicit field adapter for the unchanged TXE label output; no fallback."""
import pandas as pd
import governance as g
import driver

def core():
    f=driver.csvread(g.WORK/'inputs/features.csv')
    labels=driver.csvread(g.WORK/'execution/model/labels.csv')
    attempts=driver.csvread(g.WORK/'execution/model/attempts.csv')
    if not f.index.equals(labels.index) or not f.index.equals(attempts.index):
        raise ValueError('Exact feature/label/attempt axes required')
    for name in ('end_l0','end_l1'): labels[name]=pd.to_datetime(labels[name])
    attempts.release_date=pd.to_datetime(attempts.release_date)
    for name in ('filled','closed'):
        if attempts[name].dtype!=bool: raise ValueError('Actual booleans required')
    return f,labels,attempts
