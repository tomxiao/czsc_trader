"""Open a reviewed fixed interaction diagnostic within the new stage-three budget."""
from datetime import date
from hashlib import sha256
import argparse
import json
from pathlib import Path
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig

ROOT = Path.cwd()

def read(path):
    return json.loads(path.read_bytes())

def save(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('recipe',type=Path)
    parser.add_argument('--expected-experiment',required=True)
    parser.add_argument('--resume-setup',action='store_true')
    args = parser.parse_args()
    args.recipe = args.recipe.resolve()
    recipe = read(args.recipe)
    previous = ROOT/recipe['source_experiment']
    assert sha256((previous/'others/summary.json').read_bytes()).hexdigest() == recipe['source_summary_sha256']
    pub = read(previous/'others/publication.json')
    assert pub['validation']['status'] == 'PASS'
    assert read(previous/'others/budget_settlement.json')['status'] == 'SETTLED_ONCE'
    old = read(previous/'protocols/search.json')
    intent = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['stage'] == 'STAGE_THREE' and not intent.get('active_experiment')
    budget = intent['continuous_stage3_budget']
    number = budget['used_rounds']+1
    assert budget['authorized_rounds'] == 10 and number <= 10
    assert budget['rounds'][-1]['experiment'] == previous.name
    first = read(previous/'protocols/run_manifest.json')['next_candidate_start']
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    context = create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    if args.resume_setup:
        exp = d.ExperimentRef('S019',args.expected_experiment)
        assert exp.resolve(ROOT).is_dir() and not (exp.resolve(ROOT)/'others/results.json').exists()
        assert not (exp.resolve(ROOT)/'protocols/continuation.json').exists()
    else:
        exp = create_experiment(context,ExperimentRequest('领先配置的局部交互诊断',
            '检查三族联合优化后的领先配置是否重现ATR敏感性，辨别退出宽度与参与仓位的交互。',date(2026,11,11)))
    work = exp.resolve(ROOT)
    assert work.name == args.expected_experiment
    sources = {'setup.py':Path(__file__), 'prepare_diagnostic_recipe.py':args.recipe.parent/'prepare_diagnostic_recipe.py',
        'batch_runner.py':args.recipe.parent/'batch_runner.py',
        'prepare_audit.py':args.recipe.parent/'generic_fixed_audit.py',
        'semantic_audit.py':ROOT/'research/S019/experiments/EX046_20261111/src/semantic_audit.py',
        'close_round.py':args.recipe.parent/'close_round.py','strategy.py':previous/'src/strategy.py',
        'analyze_search.py':previous/'src/analyze_search.py',
        'analyze_diagnostics.py':args.recipe.parent/'analyze_diagnostics.py'}
    for name,path in sources.items():
        (work/'src'/name).write_bytes(path.read_bytes())
    save(work/'protocols/diagnostic_design.json',recipe['diagnostic_design'])
    save(work/'protocols/selected_centers.json',recipe['selected'])
    save(work/'protocols/diagnostic_points.json',recipe['observations'])
    save(work/'protocols/specs.json',{'base_candidate':old['base_candidate'],'candidate_start':first,
        'parameter_schema':old['parameter_schema'],'state_schema':old['state_schema'],
        'round_budget':{'allocated_rounds':10,'round_index':number,'total_round':number,'remaining_after_completion':10-number},
        'specs':recipe['specs']})
    save(work/'protocols/continuation.json',{'previous_report':pub['report'],
        'authorization_decision':budget['authorization_decision'],'selection_rule':recipe['selection_rule'],
        'recipe_sha256':sha256(args.recipe.read_bytes()).hexdigest(),
        'source_origins':{k:{'path':v.relative_to(ROOT).as_posix(),'sha256':sha256(v.read_bytes()).hexdigest()} for k,v in sources.items()}})
    plan = f'''# 新授权第{number}轮：领先参数的交互与敏感性诊断

承接上一轮三族原六门通过后最高未舍入NAR配置，同时保留各族原型控制；相同配置只计算一次，中心见selected_centers.json。正式目标、源码、样本、费率与执行合同保持。用固定因素对照回答：优化所得改善是否在邻近仓位和退出配置下持续，哪组交互最易触发绩效跳变？

每个锚点包含中心、各有效连续轴相对上下5%、两渐进族ATR距离与退出宽度的四个联合角点、参与q/t/h三轴的八角点、全部有效轴同时上下5%。完整显式列表见specs.json及diagnostic_points.json，共{len(recipe['specs'])}个不同配置。其中{sum('reuse_account' in s for s in recipe['specs'])}点复用EX046精确同源码、同参数与同执行输入的历史证据，显式保留原候选ID与旧请求；准备当前handle后仅允许实验归属不同。宽度全部保留，硬退出w无效而固定。固定点设计用于明确的交互对照，Optuna用于参数搜索；本轮结果将反馈后续开发方向。

中心先复算上一轮完整经济路径。12账户进程各1原生线程，同一TDR会话共享输入和同费用买持，检查点恢复逐项验证。独立业务审计覆盖各组中心、控制、最低Calmar、最大MDD和首个频率失败（若有），以及全局最大MDD。全部结果按原中心六门完整报告，同时统计邻点经济条件NAR≥50%、Calmar≥4.5、MDD≤25%且≤同费买持90%的有限设计通过数。

主要比较：各单轴对NAR/Calmar/MDD的变化，退出二轴与参与三轴角点，全部同向扰动是否削弱优势。联合角点明显劣化而单轴平稳时，支持继续联合优化；退出宽度缩小时敏感性重现，优先研究宽区间的达标余量；各组结果连贯且收益来源可解释时，可作为阶段三收口证据之一。

该点集用于已见开发池诊断，实际点数及分母固定，不代替正式完整局部联合邻域及≥80%验收。跨组反向联动，尤其weak_fraction与退出、参与组之间的组合，未被系统覆盖。正式阶段四尚待用户批准。全部原六门达标配置保留，正式排序仍为原六门后NAR，不新增诊断评分。
'''
    (work/'protocols/plan.md').write_bytes(plan.encode())
    intent.update(active_experiment=exp.to_dict(),active_round_budget={'round':number,'allocated_rounds':10,'remaining_after_completion':10-number},
        continuous_stage3_status='ROUND_PREPARING',next_action='通过固定交互对照辨别领先配置的敏感方向，再决定优化或收口。')
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='在新10轮阶段三授权内，依据首轮结果开展开发性参数交互诊断。')
    print('DIAGNOSTIC_OPENED',work.name,len(recipe['specs']),'round',number)

if __name__ == '__main__':
    main()
