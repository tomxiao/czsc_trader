"""518850: only verified volume-unit errors are repairable; prices fail closed."""
from .gold_etf_volume import repair_volume, volume_reference_dates
from .model import RepairPatch


def _reference_dates(daily, patch, series, findings):
    return volume_reference_dates(daily, series, findings)


PATCH = RepairPatch("TUSHARE_518850_V1", 1, "tushare", "518850.SH",
                    repair_volume, reference_dates=_reference_dates)
