"""Complete EX052/EX053 training scatter; runs only after both statistics audits PASS."""
from hashlib import sha256
import json
import math
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'.tmp/s017-family-figure-mpl'
CONFIG.mkdir(parents=True,exist_ok=True)
os.environ['MPLCONFIGDIR']=str(CONFIG)
os.environ['TEMP']=os.environ['TMP']=str(CONFIG)


def digest(path):return sha256(path.read_bytes()).hexdigest()


def main():
    from czsc_trader.research_tools import EvidenceRef
    families={};audits={};refs={}
    for experiment in ('EX052','EX053'):
        audit_path=ROOT/'.tmp'/('s017_'+experiment.lower()+'_statistics_audit_result.json')
        if not audit_path.is_file():raise ValueError('Do not generate a figure before both final audits exist')
        audit=json.loads(audit_path.read_bytes())
        if audit['status']!='PASS':raise ValueError('Both full-statistics audits must PASS first')
        ref=EvidenceRef.from_dict(audit['family_reference']);p=ref.resolve(ROOT)
        if ref.experiment.strategy_id!='S017' or ref.experiment.experiment_id!=experiment+'_20261031':raise ValueError('Wrong public family')
        if digest(p)!=ref.sha256 or ref.sha256!=audit['source_trial_table_sha256']:raise ValueError('Public family/audit bytes differ')
        data=json.loads(p.read_bytes())
        if data['status']!='COMPLETED_PARAMETER_SEARCH' or data['test_access'] or data['new_data']:raise ValueError('Incomplete or unauthorized family boundary')
        families[experiment]=data;audits[experiment]={'path':audit_path.relative_to(ROOT).as_posix(),'sha256':digest(audit_path)};refs[experiment]=ref.to_dict()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.lines import Line2D
    import numpy as np
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if not font.is_file():raise ValueError('The verified Microsoft YaHei font is unavailable')
    font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=str(font)).get_name(),
                         'axes.unicode_minus':False,'font.size':11,'figure.facecolor':'white'})
    colors={'EX052':'#2865A8','EX053':'#D46E26'}
    fig,ax=plt.subplots(figsize=(12.3,7.5),dpi=180)
    fig.subplots_adjust(left=.085,right=.755,bottom=.145,top=.88)
    all_rows=[];joint=[];frontier_ids={};scatter_counts={};counts={};handles=[]
    for experiment in ('EX052','EX053'):
        data=families[experiment];rows=[r for r in data['unique_results'] if r['status']=='SUCCEEDED']
        counts[experiment]={'successful_unique':len(rows),'unplotted_non_successful_unique':len(data['unique_results'])-len(rows)}
        x=np.array([r['metrics']['bar_max_drawdown']*100 for r in rows]);y=np.array([r['metrics']['annualized_return']*100 for r in rows])
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):raise ValueError('Finite original metrics required')
        if experiment=='EX052':
            scatter=ax.scatter(x,y,s=35,marker='o',color=colors[experiment],edgecolors='white',linewidths=.4,alpha=.75,zorder=3)
        else:
            scatter=ax.scatter(x,y,s=56,marker='^',facecolors='none',edgecolors=colors[experiment],linewidths=1.05,alpha=.85,zorder=4)
        if not np.array_equal(scatter.get_offsets().data,np.c_[x,y]):raise ValueError('Display coordinates differ from full original metrics')
        scatter_counts[experiment]=len(scatter.get_offsets())
        if scatter_counts[experiment]!=len(rows):raise ValueError('Not all successful family configurations were plotted')
        handles.append(Line2D([],[],linestyle='none',marker='o' if experiment=='EX052' else '^',
                              markerfacecolor=colors[experiment] if experiment=='EX052' else 'none',markeredgecolor=colors[experiment],
                              label=experiment+'：'+('3' if experiment=='EX052' else '4')+'维，'+str(len(rows))+'配置'))
        ids=data['return_drawdown_frontier'];frontier_ids[experiment]=ids
        front=[r for r in rows if r['candidate_id'] in ids]
        front.sort(key=lambda r:(r['metrics']['bar_max_drawdown'],r['metrics']['annualized_return']))
        ax.plot([r['metrics']['bar_max_drawdown']*100 for r in front],[r['metrics']['annualized_return']*100 for r in front],
                linestyle='--',linewidth=1.3,color=colors[experiment],alpha=.8,zorder=2)
        handles.append(Line2D([],[],linestyle='--',color=colors[experiment],label=experiment+' 观测前沿'))
        for r in rows:
            c,b=r['metrics'],r['benchmark_metrics']
            flags=(c['annualized_return']>=1.5*b['annualized_return'] if b['annualized_return']>0 else c['annualized_return']>0,
                   c['bar_max_drawdown']<=.8*b['bar_max_drawdown'],c['bar_max_drawdown']<=.25,
                   c['rolling_60_closed_cycle_median']>=6,c['coverage_at_least_three']>=.9)
            if all(flags)!=r['all_goals_met']:raise ValueError('Original five-goal AND differs')
            if all(flags):joint.append((experiment,r))
        all_rows.extend(rows)
    baseline=next(r for r in families['EX052']['unique_results'] if r['candidate_id']=='C0115')
    if baseline['parameters']!={'alpha':0.,'initial_fraction':0.,'accepted_fraction':0.}:raise ValueError('Verified baseline identity differs')
    bx,by=baseline['metrics']['bar_max_drawdown']*100,baseline['metrics']['annualized_return']*100
    ax.scatter([bx],[by],marker='*',s=180,color='#202731',edgecolors='white',linewidths=.7,zorder=6)
    ax.annotate('C113 基线',(bx,by),xytext=(bx-4.,by+40.),textcoords='data',
                ha='center',va='bottom',fontsize=10,color='#202731',
                arrowprops={'arrowstyle':'-','color':'#6B7785','linewidth':.7})
    handles.append(Line2D([],[],linestyle='none',marker='*',markersize=12,color='#202731',label='C113 原金融基线'))
    joint_ids=[]
    for n,(experiment,r) in enumerate(joint):
        x,y=r['metrics']['bar_max_drawdown']*100,r['metrics']['annualized_return']*100
        ax.scatter([x],[y],s=150,facecolors='none',edgecolors='#15734D',linewidths=1.8,zorder=7)
        ax.annotate(r['candidate_id'],(x,y),xytext=(7,9 if n%2==0 else -16),textcoords='offset points',fontsize=9,color='#15734D')
        joint_ids.append({'family':experiment,'candidate_id':r['candidate_id']})
    handles.append(Line2D([],[],linestyle='none',marker='o',markerfacecolor='none',markeredgecolor='#15734D',markersize=11,
                          label='原五门联合通过：'+str(len(joint))))
    target=1.5*baseline['benchmark_metrics']['annualized_return']*100
    if not math.isclose(target,247.63395557352264,rel_tol=1e-12):raise ValueError('Frozen annualized target changed')
    ax.axvline(25.,color='#A64145',linestyle=':',linewidth=1.6,zorder=1)
    ax.axhline(target,color='#A64145',linestyle=':',linewidth=1.6,zorder=1)
    xmax=max(25.,bx,*[r['metrics']['bar_max_drawdown']*100 for r in all_rows])*1.11
    ymin=min(0.,*[r['metrics']['annualized_return']*100 for r in all_rows]);ymax=max(target,by,*[r['metrics']['annualized_return']*100 for r in all_rows])
    ax.set_xlim(0.,xmax);ax.set_ylim(ymin-.035*(ymax-ymin),ymax+.1*(ymax-ymin))
    ax.text(25.3,ax.get_ylim()[1]-.025*(ax.get_ylim()[1]-ax.get_ylim()[0]),
            '25% 回撤线',va='top',ha='left',fontsize=10,color='#A64145')
    ax.text(xmax*.985,target,'年化目标 247.633956% ',va='bottom',ha='right',fontsize=10,color='#A64145')
    ax.set_xlabel('BAR_CLOSE 最大回撤（%，30分钟收盘取样）')
    ax.set_ylabel('净年化收益（%）')
    ax.grid(True,color='#D8DFE6',linewidth=.65,alpha=.7);ax.set_axisbelow(True)
    fig.suptitle('S017 两族完整训练配置：收益与回撤',x=.085,y=.965,ha='left',fontsize=18,fontweight='bold')
    fig.text(.085,.915,'2024-01-02—2025-12-31；全资金0或1，只做多、不加杠杆',fontsize=11,color='#526170')
    ax.legend(handles=handles,loc='upper left',bbox_to_anchor=(1.02,1.),frameon=False,fontsize=10,labelspacing=.85)
    note=('所有成功参数配置均已绘制。\n重合点不作坐标抖动。\n\n前沿仅按收益与回撤，\n不等于五门联合通过。\n\n联合标记同时核对：\n收益、相对/绝对回撤、\n两项滚动交易频率。\n\n同一训练反复选择，\n各配置并非独立样本。')
    ax.text(1.035,.43,note,transform=ax.transAxes,ha='left',va='top',fontsize=9.5,color='#526170',linespacing=1.5)
    fig.text(.085,.065,'前沿连接仅引导阅读；图示为训练结果，不代表独立验证、阶段四或采用资格。',fontsize=9.5,color='#526170')
    fig.text(.085,.035,f'年化线=同期买持{baseline["benchmark_metrics"]["annualized_return"]*100:.6f}%×1.5；C113为研究基线；每侧费用0.1%。',fontsize=9.5,color='#526170')
    output=ROOT/'.tmp/s017_ex052_ex053_returns_drawdown.png'
    fig.savefig(output,dpi=180,facecolor='white');plt.close(fig)
    provenance={'status':'GENERATED_AWAITING_VISUAL_QA','source_sha256':digest(Path(__file__)),'png_sha256':digest(output),
                'public_family_refs':refs,'independent_statistics_audits':audits,'population_counts':counts,
                'actual_scatter_counts':scatter_counts,'jitter_applied':False,'frontier_ids':frontier_ids,'joint_pass_configurations':joint_ids,
                'annualized_target_percent':target,'absolute_drawdown_target_percent':25.,'matplotlib_version':matplotlib.__version__,
                'font_resource':'Windows Fonts/msyh.ttc','font_sha256':digest(font),'baseline_metrics_source':'C0115, independently verified complete economic projection equal to C0113',
                'new_account_replays':0,'new_SE_certifications':0,'new_data_requests':0,'sealed_2026_access':False}
    p=ROOT/'.tmp/s017_two_family_figure_provenance.json';p.write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TWO_FAMILY_FIGURE_GENERATED',str(output),digest(output),flush=True)
    print('PLOT_COUNTS',scatter_counts,'JOINT_COUNT',len(joint),flush=True)


if __name__=='__main__':main()
