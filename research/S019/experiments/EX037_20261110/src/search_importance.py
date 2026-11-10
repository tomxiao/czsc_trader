"""Use Optuna's sklearn-backed fANOVA to describe the retained search history."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "research/S019/experiments/EX013_20261110/src"))
from runner import save  # noqa: E402
import json  # noqa: E402
import optuna  # noqa: E402
import sklearn  # noqa: E402


def main(experiment):
    work = ROOT / "research/S019/experiments" / experiment
    design = json.loads((work / "protocols/search.json").read_bytes())
    history = json.loads((work / "others/trials.json").read_bytes())["trials"]
    assert len(history) == design["trial_budget"] and all(t["state"] == "COMPLETE" for t in history)
    distributions = {}
    for name, b in design["space"].items():
        cls = optuna.distributions.IntDistribution if b["kind"] == "int" else optuna.distributions.FloatDistribution
        distributions[name] = cls(b["low"], b["high"], step=b["step"])
    study = optuna.create_study(direction="maximize")
    for trial in history:
        study.add_trial(optuna.trial.create_trial(params=trial["parameters"], distributions=distributions,
            value=trial["value"], user_attrs={"constraints": trial["constraints"]}))
    measures = {"nar": None, "sum_normalized_constraint_violation": lambda t: sum(max(0., c) for c in t.user_attrs["constraints"])}
    result = {}
    for name, target in measures.items():
        evaluator = optuna.importance.FanovaImportanceEvaluator(n_trees=64, max_depth=8, seed=20261110)
        result[name] = optuna.importance.get_param_importances(study, evaluator=evaluator, target=target)
    save(work / "others/search_importance.json", {"method": "Optuna FanovaImportanceEvaluator, sklearn random forest",
        "optuna_version": optuna.__version__, "sklearn_version": sklearn.__version__, "n_trees": 64, "max_depth": 8,
        "seed": 20261110, "observations": len(history), "importance": result,
        "scope": "Post-search exploratory description of the sampled parameter distribution; adaptive selection and limited coverage affect attribution. Formal acceptance remains full-account hard gates."})
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
