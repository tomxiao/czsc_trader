"""Prepare independent verification source, without reading research data."""

from pathlib import Path

HERE = Path(__file__).parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").exists())
old = (ROOT / ".tmp/s013-multiday-pressure/driver.py").read_text("utf-8")
start = old.index("    checks = 0\n", old.index("def verify():"))
end = old.index("    prices = frame(public", start)
source = old[start:end]
source = source.replace(
    "                checks += 1\n            for model, records",
    """                checks += 1
            for model, records""",
)
source = source.replace(
    '                predicted = np.array([v["prediction"] for v in records])',
    """                predicted = np.array([v["prediction"] for v in records])
                baseline = np.array([v["baseline"] for v in records])
                for year in np.unique(dates.year):
                    first = features.index[features.index.year == year][0]
                    train = mask & finite & (features.index.year >= 2020) & (features.index.year < year) & (ends < first).to_numpy()
                    np.testing.assert_allclose(baseline[dates.year == year], labels.loc[train, label].mean(), rtol=0, atol=1e-15)
                    checks += 1""",
)
source = source.replace(
    "                checks += 1\n    # Independently",
    """                    np.testing.assert_allclose(aggregate["baseline_mse"], np.mean((truth-baseline)**2), rtol=0, atol=1e-15)
                    np.testing.assert_allclose(aggregate["mse_improvement"], aggregate["baseline_mse"]-aggregate["mse"], rtol=0, atol=1e-15)
                checks += 1
    # Independently""",
)
header = '''"""Independent recomputation of published rank/DF, maturity and prediction MSE."""
import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
import opportunity_statistics as stats


def verify_statistics(features, labels, scopes, result):
'''
(HERE / "independent_statistics.py").write_text(header + source + "    return checks\n", "utf-8")
