"""Presentation-only plot spacing correction from completed analysis; no account reads."""
from hashlib import sha256
import json
from pathlib import Path
import runpy

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
WORK = Path(__file__).resolve().parents[1]
analysis = runpy.run_path(str(WORK/'src/analyze_families.py'),run_name='plot_render_context')
import matplotlib.pyplot as plt  # noqa: E402

result_path = WORK/'others/family_comparison.json'
result = json.loads(result_path.read_bytes())
assert result['status']=='COMPLETE'
assert result['sources']['analysis_sha256']==sha256((WORK/'src/analyze_families.py').read_bytes()).hexdigest()
summary = json.loads((WORK/'others/summary.json').read_bytes())
controls = {name:next(r['name'] for r in summary.values() if r['family']==name and r['trial_number']==0)
            for name in result['families']}
prior_plot_hash = result['tradeoff_plot']['sha256']
with plt.rc_context({'figure.constrained_layout.h_pad':.24}):
    rendered = analysis['plot_tradeoff'](summary,result['families'],controls,result['sources'])
rendered.update(rendering_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                original_render_sha256=prior_plot_hash,
                correction='Increase constrained-layout vertical padding so footnote and x-axis label remain separate; identical data and selection.')
result['tradeoff_plot'] = rendered
result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
print('PLOT_SPACING_CORRECTED',rendered['sha256'])
