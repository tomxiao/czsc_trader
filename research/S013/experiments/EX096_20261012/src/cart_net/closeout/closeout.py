"""EX096 original14 shallow CART fixed native centre rejection."""
from pathlib import Path
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import native_failure_closeout as final  # noqa: E402

if __name__=='__main__':
    final.close(96,'cart_net',title='固定浅树表达原14项净机会',
        judgment='浅树实际中心仅通过盈利年份频率：年化−2.23%、回撤39.94%，盈利年份101笔达标，收益、年度回撤和下跌年盈利均失败。',
        explanation='浅树把原信息分成几组条件，确实找到更多可以买的时点，却没有买到更可靠的盈利机会。固定深度2、叶至少40个成熟样本，没有新增市场信息，也没有试别的深度救援。原净价签并不等于固定1%限价规则下的实际利润。',
        positive_evidence='盈利年份101笔/1152交易日，每60日5.26笔，明确超过77笔要求；2023实际收益+10.41%、2025+17.51%，保留局部年度改善。2020没有足够过去年度训练，按事前定义不交易、不用当年未来标签补训练。',
        counterevidence='2022实际−30.45%、2026截至截止日−6.72%；全期年化−2.23%、回撤39.94%，虽有154笔总闭合但盈利质量不够。固定贪心树还无法识别无根SSE改善的对称XOR，合成条件组合可拟合不证明真实优势。中心失败，32/双费未运行，Q10/Q90不可得。',
        next_direction='下一轮检验Huber稳健回归是否减少极端训练样本的影响；不改本轮树深/叶阈值。最后按已固定三模型当前多数准入表达做独立对照，完成额度即暂停。',
        caller=Path(__file__))
