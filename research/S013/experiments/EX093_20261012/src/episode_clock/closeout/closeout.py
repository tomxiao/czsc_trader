"""EX093 actual market-clock centre scientific rejection."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import native_failure_closeout as final  # noqa: E402


if __name__=='__main__':
    final.close(93,'episode_clock',title='机会窗口独立计时，能否减轻参数引发的连锁变化',
        judgment='独立市场TIME时钟未改善中心经济：净年化12.50%、回撤19.19%、盈利年份67笔不足77，2023转为−0.61%；收益/逐年回撤两门通过，另两门失败，停止固定表达。',
        explanation='通俗说，从市场机会出现时开始计时，确实让计时不再跟着买入日期改变，但晚买可能很快到期。独立计时也会改变下一笔买入和现金路径，实际收益变低、回撤变大；减少状态依赖不等于稳健达标。',
        positive_evidence='中心仍有12.50%净年化，高于10.829%门槛；每个自然年回撤严格小于buyhold；2022实际+12.33%、2024+54.84%。不删除仍通过两门与正收益事实。',
        counterevidence='原C8880净年化17.13%/回撤13.62%，新为12.50%/19.19%；2023由+0.918%转−0.610%，盈利年闭合68降67。计时只与市场独立，交易anchor/peak/TIME-BELOW记忆仍反馈；episode资格/范围/期限的参数边界也仍存在。未运行32，不能宣称路径或绝对扰动尾部改善。',
        next_direction='下一不同职责检验是先取得已知信号浮盈后再锁存入场锚保护，控制原其他规则，明确该锚不是实际成本或保证保本；不调整本轮episode期限来救援。',
        caller=Path(__file__))
