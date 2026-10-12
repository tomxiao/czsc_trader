"""EX094 fixed signal-profit latch full-centre rejection."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import native_failure_closeout as final  # noqa: E402


if __name__=='__main__':
    final.close(94,'profit_latch',title='先取得浮盈，再启用入场锚价撤退保护',
        judgment='浮盈激活后锚价保护未改善中心：净年化16.31%、回撤15.42%，盈利年份仍68笔不足77，2023由正转−1.19%；收益/逐年回撤通过，另两门失败，停止固定表达。',
        explanation='通俗说，先赚过一点再撤退，也可能提前卖掉随后反弹的机会。它没有增加所需的盈利年份交易，而且后续重入和费用使2023转亏。锚价是信号入场Close，次日成交可能不同，不表示实际扣费保本。',
        positive_evidence='仍通过总体收益门和全部年度回撤门；2022实际+18.40%、2024+65.00%；2020/2021与原规则精确相同，没有人为重算这些控制年份。',
        counterevidence='CAGR17.13%→16.31%，全期回撤13.62%→15.42%，2023+0.918%→−1.186%，2025+11.08%→+9.47%；116总闭合及68盈利年闭合都未增加。它新增激活边界，不能由单向latch推断更强参数稳健；未运行32，Q10/Q90不可得。',
        next_direction='下一轮改检验参与职责：仅在当日和前日均因果rawbull且严格正BODY时解除确认分门，保留边界及下行确认；不再调整本轮波动窗口/激活倍数寻找事后好结果。',
        caller=Path(__file__))
