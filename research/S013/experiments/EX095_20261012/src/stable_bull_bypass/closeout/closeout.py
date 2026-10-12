"""EX095 fixed stable-bull confirmation bypass centre closeout."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import native_failure_closeout as final  # noqa: E402

if __name__=='__main__':
    final.close(95,'stable_bull_bypass',title='连续上行且当日收涨时放过买入确认分门',
        judgment='中心三门通过但盈利年份频率仍失败：年化14.72%、回撤13.62%，盈利年份70笔低于77笔要求，停止本固定表达。',
        explanation='只在连续两天处于当时可知的上行状态、当天收盘高于开盘时，允许原本被确认分拒绝的买入。增加了两笔盈利年份交易，却降低了总体收益；增加参与次数没有自动带来有效参与。年度最终盈亏没有进入决策。',
        positive_evidence='总体收益、逐年回撤及两个下跌年份盈利三门仍通过；2022收益19.59%、2023收益0.918%；2021从8.29%小幅升至8.56%，全期回撤13.6187%微降至13.6178%，均保留但不夸大。',
        counterevidence='盈利年份68→70笔，仍差7笔；总闭合116→118笔，年化17.13%→14.72%；2024收益65.02%→57.96%，2025收益11.08%→8.32%，2026截至研究截止日−0.039%→−4.87%。中心失败，32点与双费未运行，Q10/Q90及扰动达标率不可得。',
        next_direction='接下来分别检验固定浅树及Huber稳健回归对原14项信息的不同表达，最后检验三种表达的当前入场多数一致；不再调整本轮旁路条件救援。所有阶段均保留新版中心及全部32点四门要求。',
        caller=Path(__file__))
