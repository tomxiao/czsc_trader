"""Retain the failed age contract without overwriting it with successor results."""
from hashlib import sha256
from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope)
from run import WORK,REPOSITORY,EXPERIMENT,context,read,save,material

def main():
    status=read(WORK/'others/execution_status.json')
    if len(status)!=3 or any(row['status']!='FAILED' or 'AUXILIARY_INPUT_STALE' not in row['error']['message'] for row in status):
        raise ValueError('failure evidence differs')
    report='''# EX010 技术失败，未形成收益结论

三项正式请求均因辅助日线最大年龄96小时过紧而失败，未发布账户；此结果不能用于评价市场或行业收益假设。
原预检仅验证合成执行，未覆盖半日市接长周末的日线年龄边界。

公共DFLS时间戳核对确认：2020-12-28与2025-07-07各5个决策点距前次半日收盘超过96小时，最大98.5小时。
SPY和XLK行情均完整，不存在用陈旧资料替代缺失新日线的事实。证据见[时间戳核验](others/auxiliary_age_audit.json)。

原策略、配置、定义及失败状态保持不变。后继EX013使用新的候选身份，明确最大年龄5个自然日；
不改策略逻辑、市场数据、费用、窗口或基准。此修订仅依据日历事实，没有候选收益反馈。
本轮计入20轮额度，归为技术失败，不计成功正式账户或完成的收益假设验证。
'''
    (WORK/'report.md').write_bytes(report.encode())
    ctx=context(1)
    refs=[EvidenceRef.from_dict(ref) for ref in read(WORK/'others/pre_run_evidence.json').values()]
    for name,path in [('execution-status','others/execution_status.json'),('execution-stats','others/execution_stats.json'),('age-audit','others/auxiliary_age_audit.json'),('failure-publisher','src/publish_failure.py')]:
        refs.append(material(ctx,name,WORK/path))
    reference=publish_evidence(ctx,ExperimentReportWrite(EXPERIMENT,sha256(report.encode()).hexdigest(),ExperimentOutcome.FAILED,tuple(refs)))
    validation=validate_experiment(REPOSITORY,ExperimentValidationRequest(EXPERIMENT,ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/failure_publication.json',{'report':reference.to_dict(),'validation':validation.to_dict()})
    assert validation.status.value=='PASS'
    print('FAILED report retained; publication validation PASS')

if __name__=='__main__':
    main()
