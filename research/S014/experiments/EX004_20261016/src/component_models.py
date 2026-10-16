"""Fixed estimators and paired time-block diagnostics; no parameter search."""
import numpy as np


def predict(task):
    train_x, test_x, train_y = (np.asarray(value, dtype=float) for value in task)
    means = np.nanmean(train_x, axis=0)
    if not np.isfinite(means).all():
        raise ValueError("training feature column has no finite values")
    left = np.where(np.isfinite(train_x), train_x, means)
    right = np.where(np.isfinite(test_x), test_x, means)
    scale = left.std(axis=0)
    scale[scale < 1e-12] = 1.0
    left, right = (left - means) / scale, (right - means) / scale
    center = float(train_y.mean())
    coefficients = np.linalg.solve(left.T @ left + 10 * np.eye(left.shape[1]), left.T @ (train_y - center))
    return {"prediction": right @ coefficients + center, "train_prediction": left @ coefficients + center,
            "coefficient": coefficients,
            "train_mean": means, "train_scale": scale, "intercept": center}


def bootstrap(task):
    groups, seed = task
    random = np.random.default_rng(seed)
    count = sum(len(values) for values in groups)
    distribution = np.zeros(5000)
    for values in groups:
        values = np.asarray(values, dtype=float)
        blocks = int(np.ceil(len(values) / 20))
        starts = random.integers(0, len(values), size=(5000, blocks))
        positions = (starts[:, :, None] + np.arange(20)) % len(values)
        positions = positions.reshape(5000, -1)[:, :len(values)]
        distribution += values[positions].sum(axis=1) / count
    return {"difference": float(sum(np.sum(x) for x in groups) / count),
            "interval_95": np.quantile(distribution, [.025, .975]).tolist(),
            "interval_familywise": np.quantile(distribution, [.05 / 24, 1 - .05 / 24]).tolist(),
            "bootstrap_draws": 5000, "block_sessions": 20}
