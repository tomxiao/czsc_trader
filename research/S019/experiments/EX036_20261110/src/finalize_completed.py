"""Finalize already completed proposals from retained public execution statistics."""
import sys
from joint_search import OWNER, read, save, summarize


def main(experiment):
    work = OWNER.parent / experiment
    config, design = read(work / "protocols/config.json"), read(work / "protocols/search.json")
    trials = read(work / "others/trials.json")["trials"]
    assert len(trials) == design["trial_budget"] and all(t["state"] == "COMPLETE" for t in trials)
    attempts = read(work / "others/attempts.json")
    stats = {key: sum(a["equity_statistics"][key] for a in attempts)
             for key in ("input_snapshots", "candidate_runs", "benchmark_runs")}
    stats["account_timings"] = [t for a in attempts for t in a["equity_statistics"]["account_timings"]]
    save(work / "others/execution.json", {**attempts[-1], "equity_statistics": stats,
        "prepare_seconds": sum(a["prepare_seconds"] for a in attempts),
        "evaluate_seconds": sum(a["evaluate_seconds"] for a in attempts),
        "total_seconds": sum(a["total_seconds"] for a in attempts), "attempt_count": len(attempts),
        "statistics_scope": "LAST_ATTEMPT; full per-attempt statistics retained in attempts.json"})
    summarize(work, config)
    summary, measured = read(work / "others/summary.json"), read(work / "others/search_results.json")
    assert all(summary[name]["candidate"] == row["candidate"] for name, row in measured.items())
    print("JOINT_SEARCH_COMPLETE", design["parent"], len(trials), len(summary), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
