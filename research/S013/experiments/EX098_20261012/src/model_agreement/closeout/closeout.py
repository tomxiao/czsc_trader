"""EX098 final quota fixed model admission agreement native rejection."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import native_failure_closeout_v2 as final  # noqa: E402

if __name__=='__main__':
    final.close(98,'model_agreement',title='三模型当前两票同意准入及单持仓时钟',
        judgment='最后一轮实际中心仍仅频率达标：年化−0.73%、回撤43.16%，盈利年份115笔，2022亏损28.67%、2023亏损3.15%；十轮额度已用完，目标未达成，暂停研究。',
        explanation='三种模型共同同意，并没有消除它们共享信息中的错误。盈利年份交易115笔足够，2025赚23.96%仍难弥补下跌期损失。相比单浅树或Huber，年化亏损缩小，但回撤更大，不能视为满足要求的进展。',
        positive_evidence='盈利年份115笔/1152日、每60日5.99笔达标；2021实际11.27%、2025实际23.96%，保留局部改善。三模型训练来源、全三可得条件、当前严格两票正准入和唯一H时钟均独立核验；没有按最终年度盈亏选模型或事后调票数。',
        counterevidence='总体年化−0.73%、回撤43.16%，185笔总闭合；2022−28.67%、2023−3.15%。三模型同源价量和标签，投票不构成独立信息，Huber位置及票数也不等于净期望收益。当前两票准入和共用时钟不同于EX018虚拟持仓票决，但仍未产生达标净优势。中心失败，32/双费未运行，Q10/Q90不可得。',
        next_direction='EX089–EX098已完成10/10，剩余0，无EX099；完成交付、副本与额度终核后暂停。保留C8880基准和买入质量约束、各轮局部有利反证；停止这批固定校准/更新/交互/退出/旁路/浅树/Huber/投票表达。若以后获得新授权，优先检验与实际成交及持仓占用一致的净机会定义，并先证明对旧信息有增量；这是待验证方向，不是本轮已证明的失败根因。',
        caller=Path(__file__))
