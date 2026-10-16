"""A fixed nonlinear expression control and disclosed familywise diagnostics."""
import numpy as np
from sklearn.tree import DecisionTreeRegressor
from component_models import predict


def fit(task):
    estimator, train_x, test_x, train_y = task
    if estimator == "ridge":
        return predict((train_x, test_x, train_y))
    if estimator != "tree":
        raise ValueError("Unknown declared estimator")
    means = np.nanmean(train_x, axis=0)
    if not np.isfinite(means).all():
        raise ValueError("Training feature column is empty")
    left = np.where(np.isfinite(train_x), train_x, means)
    right = np.where(np.isfinite(test_x), test_x, means)
    model = DecisionTreeRegressor(max_depth=2, min_samples_leaf=50, random_state=13)
    model.fit(left, train_y)
    return {"prediction": model.predict(right), "train_prediction": model.predict(left)}


def interval(task):
    groups, seed = task
    random = np.random.default_rng(seed)
    size = sum(len(x) for x in groups)
    distribution = np.zeros(5000)
    for group in groups:
        count = len(group)
        starts = random.integers(0, count, (5000, int(np.ceil(count / 20))))
        indices = ((starts[:, :, None] + np.arange(20)) % count).reshape(5000, -1)[:, :count]
        distribution += np.asarray(group)[indices].sum(axis=1) / size
    return {"difference": float(sum(np.sum(x) for x in groups) / size),
            "interval_95": np.quantile(distribution, [.025, .975]).tolist(),
            "interval_familywise": np.quantile(distribution, [.05 / 64, 1 - .05 / 64]).tolist()}
