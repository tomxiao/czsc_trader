"""EX097 fixed Huber net native centre rejection."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import native_failure_closeout as final  # noqa: E402

if __name__=='__main__':
    final.close(97,'huber_net',title='Huber稳健回归表达原14项净机会',
        judgment='稳健回归中心仅通过盈利年份频率：年化−2.15%、回撤41.39%，盈利年份107笔达标，但收益、年度回撤、两个下跌年盈利均失败。',
        explanation='让极端样本少影响拟合，仍没有产生足够好的实际买入机会。107笔盈利年份交易超过要求，但2022亏损25.41%、2023亏损1.93%。拟合稳定和策略抗扰动是不同问题；Huber估计稳健位置，也不等于平均净收益。',
        positive_evidence='盈利年份107笔/1152交易日、每60日5.57笔，频率通过；2025收益15.31%、2026截至截止日1.38%，这些局部表现保留。所有年度训练成熟来源、原14及真实IRLS最终驻点均独立核验，没有未来年度选择。',
        counterevidence='全期年化−2.15%、回撤41.39%，178笔总闭合没有形成净优势；2021−0.53%、2022−25.41%、2023−1.93%。少数大涨可能是策略必要收益来源，稳健位置并不保证更高条件净期望；MAD尺度/阈值不事后调整。中心失败，32点及双费未运行，Q10/Q90不可得。',
        next_direction='只执行已事前固定的最后一轮：联合岭回归、浅树、Huber三种当前分数至少两种为正才准入，并共用一个H持仓时钟。三模型同源且可能共同犯错，不借本轮结果换票数/权重；EX098完成后暂停。',
        caller=Path(__file__))
