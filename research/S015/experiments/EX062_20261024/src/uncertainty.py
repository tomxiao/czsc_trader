"""Descriptive paired block resampling of retained daily account returns.

No new accounts, parameter search, qualification or independent validation.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

HOME = Path(__file__).resolve().parents[1]
ROOT = HOME.parents[3]
BASE = HOME.parent


def read(p):
    return json.loads(p.read_bytes())


def account(experiment, cid):
    row = next(r for r in read(BASE/experiment/'others/results.json')['rows'] if r['candidate_id'] == cid)
    ref = EvidenceRef.from_dict(row['evidence'])
    value = read(ref.resolve(ROOT))
    run = next(r for r in value['runs'] if r['window_id'] == 'full')
    frame = pd.DataFrame(run['ledgers']['account_daily']['data'])
    equity = np.r_[100000., frame.equity.to_numpy(float)]
    return np.diff(np.log(equity)), ref.to_dict()


def main():
    pairs = [('C6105','C6102'), ('C6104','C6101'), ('C6117','C6105')]
    records=[]
    for subject,control in pairs:
        a,aref=account('EX061_20261024',subject)
        b,bref=account('EX061_20261024',control)
        diff=a-b
        item={'subject':subject,'control':control,'subject_evidence':aref,'control_evidence':bref,
              'sessions':len(diff),'mean_log_return_difference_bp':float(diff.mean()*10000),
              'method':'Paired circular moving-block resampling, 1999 replications; mean daily net log-return difference only.',
              'intervals':[]}
        for block in (10,20):
            rng=np.random.default_rng(13)
            starts=rng.integers(0,len(diff),size=(1999,int(np.ceil(len(diff)/block))))
            index=(starts[:,:,None]+np.arange(block))%len(diff)
            means=diff[index.reshape(1999,-1)[:,:len(diff)]].mean(axis=1)
            item['intervals'].append({'block_length':block,'seed':13,'replications':1999,
                'percentile95_bp':(np.quantile(means,[.025,.975])*10000).tolist(),
                'fraction_nonpositive':float(np.mean(means<=0))})
        records.append(item)
    output={'status':'COMPLETE','pairs':records,
       'limitations':['已见开发池上的事后选择比较；1999次重采样不是1999份独立市场证据。',
       '区间仅描述平均每日对数收益差，不能用作最终账户收益/回撤的置信区间。',
       '圆形块近似保留短期依赖，未证明平稳性；未矫正所有历史机制、参数和持有期限选择。',
       '未计算正式PBO/DSR或完整阶段四自检；本检查不新增验收门，也不宣称未来成功概率。']}
    (HOME/'others/uncertainty.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print([(r['subject'],r['control'],r['mean_log_return_difference_bp'],r['intervals'][0]['percentile95_bp']) for r in records])


if __name__=='__main__':
    main()
