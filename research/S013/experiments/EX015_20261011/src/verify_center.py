"""Compare all economic fields while preserving distinct generated account IDs."""
import pandas as pd
from common import ROOT,RUNS,CACHE,cache_read,write

def main():
    original=cache_read(ROOT/'.tmp/s013-mechanism-EX012/B0-M1.pkl.gz')[1].runs[0]
    candidate=cache_read(CACHE/'N8.pkl.gz')[1].runs[0]
    ignored={'decisions':('decision_id',),'orders':('order_id','decision_id','cycle_id'),
        'fills':('fill_id','order_id','decision_id','cycle_id'),'account_daily':(), 'trades':('cycle_id',)}
    fields={}
    for name,a,b in [('strategy',original.execution,candidate.execution),
        ('benchmark',original.buyhold.execution,candidate.buyhold.execution)]:
        for field,columns in ignored.items():
            left,right=getattr(a,field),getattr(b,field)
            pd.testing.assert_frame_equal(left.drop(columns=list(columns)),right.drop(columns=list(columns)),check_exact=True)
            fields[name+'/'+field]={'status':'EXACT_EQUAL economic and signal fields',
                'rows':len(left),'excluded_generated_identity_columns':list(columns),
                'raw_identity_columns_retained':'Both full native accounts remain immutable and separately referenced'}
    write(RUNS/'center_equivalence.json',{'status':'PASS','comparison':'N8 versus original C2132',
        'fields':fields,'scope':'Generated IDs differ by strategy identity; all other signal, order, fill, daily account and trade fields compared exactly.'})
    print({'center_economic_equivalence':'EXACT_EQUAL','all_five_ledger_fields':True})

if __name__=='__main__':
    main()
