"""Finalize the published delivery, preserving the original CRLF source report."""
from pathlib import Path
from hashlib import sha256
import json
from czsc_trader.application import RepositoryContext, validate_delivery, update_research_intent, ResearchIntentUpdate
from czsc_trader.research_tools import DeliveryReference, ValidationStatus
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def main():
    if (EX/'others/result.json').exists():raise RuntimeError('Preserve final result')
    receipt=read(ROOT/'research/S014/deliveries/CANDIDATES/1/receipt.json')
    ref=DeliveryReference.from_dict(receipt['reference']);repo=RepositoryContext.discover(ROOT)
    validation=validate_delivery(repo,ref);assert validation.status is ValidationStatus.PASS,validation
    formal=ROOT/'research/S014/deliveries/CANDIDATES/1/report.md'
    source=EX/'protocols/account_report.md'
    assert formal.read_bytes()==source.read_bytes().replace(b'\r\n',b'\n')
    (EX/'others/report.md').write_bytes(formal.read_bytes())
    content=read(ROOT/'research/S014/assets/deliveries/CANDIDATES/1/delivery.json')['content']
    comparison=read(EX/'others/comparison.json')
    result={'status':'COMPLETE','experiment':{'strategy_id':'S014','experiment_id':EX.name},
        'delivery':ref.to_dict(),'validation':validation.to_dict(),
        'evidence':{v['name']:v for v in content['evidence']},'account_count':4,'all_targets_pass_count':0,
        'source_calls':8,'remaining_source_calls':7,'phase_four_approved':False,'conclusion':comparison['conclusion'],
        'report_copy':{'path':(EX/'others/report.md').relative_to(ROOT).as_posix(),
                       'sha256':sha256(formal.read_bytes()).hexdigest(),'bytes_identical_to_formal':True,
                       'original_protocol_report_preserved':True,'source_difference':'CRLF vs canonical LF only'}}
    (EX/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段三四方案账户对照完成，待用户决定后续研究',strategy_accounts=4,
        candidates=ref.to_dict(),all_targets_pass_count=0,remaining_source_calls=7,phase_four_approved=False,
        conclusion=comparison['conclusion'],pending=['根据四方案账户证据决定继续阶段三优化或回退阶段二；不自动进入阶段四。'])
    intent['stage_three_preparation']['status']='ACCOUNT_COMPARISON_COMPLETE'
    intent['stage_three_preparation']['actual_account_runs']=4
    intent['stage_three_prewindow_authorization'].update(actual_calls=8,remaining_calls=7,status='COMPLETE')
    update_research_intent(repo,ref.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成四方案连续账户、年度验收和独立账本审计；正式交付FULL校验通过，0个全部达标')
    print(json.dumps({'delivery':ref.to_dict(),'validation':validation.to_dict(),'evidence':len(content['evidence']),
        'report_copy_bytes_identical':True},ensure_ascii=False))

if __name__=='__main__':main()
