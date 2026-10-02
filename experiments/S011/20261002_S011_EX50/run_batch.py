"""Single in-memory study; process-local formal experiments; no shared context."""

from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path
import json
import os
import runpy
import time
import optuna

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent


def run_one(name):
    started = time.time()
    runpy.run_path(str(BASE / name / "run_experiment.py"), run_name="__main__")
    return dict(experiment=name, pid=os.getpid(), started=started, finished=time.time())


def write(name, value):
    (ROOT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def main():
    assert not (ROOT / "batch_result.json").exists()
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[key] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    spec = json.loads((ROOT / "batch_specs.json").read_text())
    assert optuna.__version__ == spec["optuna_version"]
    study = optuna.create_study(
        storage=optuna.storages.InMemoryStorage(),
        sampler=optuna.samplers.RandomSampler(seed=spec["seed"]),
    )
    trials = []
    for slot in range(16):
        study.enqueue_trial({"slot": slot})
        trial = study.ask()
        assert trial.suggest_int("slot", 0, 15) == slot
        trials.append(trial)
    completed = []
    errors = []
    with ProcessPoolExecutor(max_workers=spec["workers"], mp_context=get_context("spawn")) as pool:
        pilot = pool.submit(run_one, spec["experiments"][0]).result()
        old = json.loads(
            (BASE / "20261002_S011_EX40/artifacts/assessment_evidence.json").read_text()
        )[0]
        fresh = json.loads(
            (BASE / spec["experiments"][0] / "artifacts/assessment/C0621.json").read_text()
        )[0]
        for key in (
            "candidate",
            "account",
            "fills",
            "closed_cycles",
            "benchmark_equity",
            "scenario_context",
        ):
            assert old[key] == fresh[key], f"Cross-process center replay differs: {key}"
        write(
            "parallel_precheck.json",
            dict(
                status="PASS",
                compared=[
                    "candidate",
                    "account",
                    "fills",
                    "closed_cycles",
                    "benchmark_equity",
                    "scenario_context",
                ],
                pilot=pilot,
            ),
        )
        completed.append(pilot)
        jobs = {
            pool.submit(run_one, name): (i, name) for i, name in enumerate(spec["experiments"][1:])
        }
        for future in as_completed(jobs):
            group, name = jobs[future]
            try:
                completed.append(future.result())
                for slot in (group * 2, group * 2 + 1):
                    study.tell(trials[slot], 0.0)
            except Exception as exc:
                errors.append(dict(experiment=name, error=str(exc)))
                for slot in (group * 2, group * 2 + 1):
                    study.tell(trials[slot], state=optuna.trial.TrialState.FAIL)
                for pending in jobs:
                    pending.cancel()
    value = dict(
        storage="InMemoryStorage",
        adaptive_search=False,
        workers=spec["workers"],
        native_threads=1,
        completed=completed,
        errors=errors,
        trials=[
            dict(number=t.number, slot=t.params["slot"], state=t.state.name) for t in study.trials
        ],
    )
    write("batch_result.json", value)
    assert (
        not errors
        and len(completed) == 9
        and all(t["state"] == "COMPLETE" for t in value["trials"])
    )
    print(
        json.dumps(
            dict(
                status="PASS",
                experiments=len(completed),
                slots=16,
                worker_pids=sorted({x["pid"] for x in completed}),
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
