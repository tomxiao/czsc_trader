"""One-time source-only specialization of authorized frozen statistical kernels."""
import ast
from hashlib import sha256
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
LABEL_SOURCE=ROOT/'.tmp/s013-volume-body-interaction/component_draft.py'
STAT_SOURCE=ROOT/'.tmp/s013-volume-body-interaction/statistics_draft_v2.py'
if sha256(LABEL_SOURCE.read_bytes()).hexdigest()!='21b8d20cea9ba67d6b45128dc764329d89f9f20dfe89baa49ed9a4b85dce6521':
    raise ValueError('Exact authorized frozen label source drift')
if sha256(STAT_SOURCE.read_bytes()).hexdigest()!='efb3e3db5ef14cee38aa74a39873b54506e6c3071d9b442d45d410435e023708':
    raise ValueError('Exact authorized frozen statistical source drift')
label_text=LABEL_SOURCE.read_text(encoding='utf-8')
node=next(n for n in ast.parse(label_text).body if isinstance(n,ast.FunctionDef) and n.name=='fee_labels4')
body=''.join(label_text.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
(HERE/'labels.py').write_text('"""Exact AST/byte function from authorized frozen EX075 pure label source."""\nimport numpy as np\nimport pandas as pd\n\n'+body+'\n',encoding='utf-8')

source=STAT_SOURCE.read_text(encoding='utf-8')
source=source.replace('"Pure fixed standby statistics. No file, provider, account or registry I/O."','"Pure fixed17-control curvature statistics. No file/provider/account/registry I/O."')
source=source.replace('    "mean_negative_body",\n    "past_volume_shape_projection",','    "short_stretch4",')
source=source.replace('COMPONENT = "down_volume_cov"','COMPONENT = "curvature4"')
source=source.replace('[:, :18]','[:, :17]').replace('fixed19 features/two labels','fixed18 features/two labels')
source=source.replace('def analyze(features, labels, price_calendar=None):','def _analyze_scope(features, labels, price_calendar=None):')
source+='''

def analyze(features, labels, price_calendar=None, *, flat_eligible):
    """Both predeclared scopes on the unchanged original full signal axis.

    Scope exclusion is represented as missing target BEFORE full-axis bootstrap,
    so every block/phase/year/maturity boundary retains original coordinates.
    All models within each scope use the same finite, mature18-column rows.
    """
    index, _, _ = validate(features, labels, price_calendar)
    if (not isinstance(flat_eligible, pd.Series) or not flat_eligible.index.equals(index)
            or flat_eligible.dtype != np.dtype(bool)):
        raise ValueError('Exact complete original causal policy-flat Boolean scope required')
    scoped = labels.copy(deep=True)
    scoped.loc[~flat_eligible, list(LABELS)] = np.nan
    result = {'status': 'DESCRIPTIVE_STATISTICS_NOT_SCIENTIFIC_OR_ECONOMIC_ACCEPTANCE',
        'primary': 'return4_net', 'return_direction': 'positive',
        'risk_role': 'diagnostic only, no fixed sign, trading role or economic gate',
        'full_axis_n': len(index), 'causal_original_policy_flat_eligible_n': int(flat_eligible.sum()),
        'scopes': {'all': _analyze_scope(features, labels, price_calendar),
            'causal_original_policy_flat_eligible': _analyze_scope(features, scoped, price_calendar)}}
    return result
'''
(HERE/'curvature_statistics.py').write_text(source,encoding='utf-8')
