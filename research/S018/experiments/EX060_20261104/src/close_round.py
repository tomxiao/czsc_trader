from pathlib import Path
import json,sys,shutil
from hashlib import sha256
from helpers import ROOT,FAMILY,TMP,read,save,BASE
n=int(sys.argv[1]); work=FAMILY/f'experiments/EX{n:03d}_20261104'
assert not (work/'report_ref.json').exists()
r=read(work/'others/results.json'); p=read(work/'others/protocol.json')
audit=read(work/'others/analysis_audit.json')
note=(TMP/f'findings{n}.md').read_text(encoding='utf-8')
refs=read(work/'others/evidence_refs.json')
for eid,cid in [(56,'C8612'),(52,'C8214')]:
 refs.append(read(FAMILY/f'experiments/EX{eid:03d}_20261104/others/results.json')['accounts'][cid]['account_ref'])
 refs.append(read(FAMILY/f'experiments/EX{eid:03d}_20261104/report_ref.json')['report'])
if n>58:refs.append(read(FAMILY/f'experiments/EX{n-1:03d}_20261104/report_ref.json')['report'])
save(work/'others/evidence_refs.json',refs)
for source,name in [(TMP/'audit.py','audit_accounts.py'),(FAMILY/'experiments/EX056_20261104/src/analyze_downside.py','analyze_downside.py'),(TMP/'close_round.py','close_round.py'),(TMP/'helpers.py','helpers.py')]:
 shutil.copyfile(source,work/'src'/name)
passed=[(cid,row) for cid,row in r['accounts'].items() if all(row['gates'].values())]
body=f'# EX{n:03d}：{p["question"]}\n\n## 范围与选择\n\n用户已授权端到端明确参数并补查。本轮为原30轮额度第{n-33}轮，余{63-n}轮；阶段三，无阶段四。原数据、开发池、D和五项硬门不变，十月及尾部仅诊断。\n\n本轮{len(r["accounts"])}个正式策略账户，{len(passed)}个通过全部原硬门。计算使用V4显式执行会话及共享买持；逐参数、实现身份、来源和负面结果见[protocol](others/protocol.json)与[results](others/results.json)。\n\n'
body+='## 研究结论\n\n'+note+'\n\n## 完整结果\n\n|候选|净年化%|回撤%|净卡玛|60日中位|覆盖%|十月收益%|全部硬门|\n|---|---:|---:|---:|---:|---:|---:|---|\n'
for cid,row in sorted(r['accounts'].items(),key=lambda x:-x[1]['candidate']['calmar']):
 m=row['candidate'];body+=f'|{cid}|{m["annual"]*100:.4f}|{m["dd"]*100:.4f}|{m["calmar"]:.6f}|{m["median"]:g}|{m["coverage"]*100:.4f}|{m["october_return"]*100:.4f}|{"PASS" if all(row["gates"].values()) else ", ".join(k for k,v in row["gates"].items() if not v)}|\n'
body+='\n## 核验与解释边界\n\n[逐日账户审计](others/analysis_audit.json)独立检查入口与行业分组、可得时序、真实成交建立的周期、预算/费用/整数限价、退出优先及最多一次成功补仓；默认参数控制与C8612经济账本精确比较。预热历史按beta窗口、入口段及持有周期联动，主输入和辅助输入一致。\n\n[路径诊断](others/analysis_downside.json)保留完整滚动窗口及固定C8214历史回撤区间；这些事后窗口不进入交易信号，也不增加硬门。全部结果来自反复使用的开发池，邻近参数和相同行为不构成独立统计试验。没有独立验证、未来盈利保证或全局最优结论。\n'
(work/'report.md').write_text(body,encoding='utf-8')
print('REPORT_READY',n)
