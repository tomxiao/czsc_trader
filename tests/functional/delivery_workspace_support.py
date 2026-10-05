"""The synthetic researcher chooses fixture locations; TDR never infers them."""

from czsc_trader.research_tools import delivery as d


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
        ids = (f"20261001_{strategy}_EX01", f"20261001_{strategy}_EX02",
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
    return d.DeliveryWorkspace(tuple(deliveries), tuple(experiments))
