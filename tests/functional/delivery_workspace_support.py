"""The synthetic researcher chooses fixture locations; TDR never infers them."""

from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools import ResearchWorkspace, CandidateLocation, FreezeJournalLocation
from strategy_manager import CandidateKey, ResearchEvidenceLocation, ResearchEvidenceOwner


def fixture_delivery_workspace():
    deliveries = []
    experiments = []
    for strategy in ("S900", "S901"):
        mandate = d.MandateOwner(strategy)
        for revision in (1, 2, 3):
            deliveries.append(d.DeliveryLocation(
                mandate, d.DeliveryStage.MANDATE, revision,
                f"research/{strategy}/mandates/{revision}",
            ))
        ids = (f"20261001_{strategy}_EX01", f"20261001_{strategy}_EX02", f"20261001_{strategy}_EX03",
               f"20261001_{strategy}_EX99", "EX078_20261003")
        for experiment_id in ids:
            owner = d.ExperimentOwner(strategy, experiment_id)
            source = f"experiments/{strategy}/{experiment_id}"
            experiments.append(d.ExperimentLocation(owner, source))
            for stage in d.DeliveryStage:
                if stage is d.DeliveryStage.MANDATE:
                    continue
                for revision in (1, 2, 3):
                    deliveries.append(d.DeliveryLocation(
                        owner, stage, revision, f"{source}/deliveries/{stage.value}/{revision}",
                    ))
    owner = d.ExperimentOwner("S008", "20260924_S008_EX99")
    source = "experiments/S008/20260924_S008_EX99"
    experiments.append(d.ExperimentLocation(owner, source))
    deliveries.append(d.DeliveryLocation(owner, d.DeliveryStage.COMPONENTS, 1,
                                        f"{source}/deliveries/COMPONENTS/1"))
    experiments.append(d.ExperimentLocation(d.ExperimentOwner("S009", "EX001_20261003"),
                                            "experiments/S009/EX001_20261003"))
    return d.DeliveryWorkspace(tuple(deliveries), tuple(experiments))


def fixture_research_workspace():
    candidates = tuple(CandidateLocation(CandidateKey("S900", name), "20261001_S900_EX01")
                       for name in ("C0001", "C0002", "C0003"))
    candidates += (CandidateLocation(CandidateKey("S009", "C0001"), "EX001_20261003"),)
    evidence = [ResearchEvidenceLocation(ResearchEvidenceOwner(strategy), f"research/{strategy}")
                for strategy in ("S900", "S901", "S009")]
    evidence.extend(ResearchEvidenceLocation(
        ResearchEvidenceOwner(x.owner.strategy_id, x.owner.experiment_id), x.path)
                    for x in fixture_delivery_workspace().experiments)
    return ResearchWorkspace(
        "research/registrations", candidates, tuple(evidence),
        tuple(FreezeJournalLocation(strategy, f"research/{strategy}/freeze_requests")
              for strategy in ("S900", "S901", "S009")),
    )
