"""Registry of isolated vendor-symbol history repair patches."""

from __future__ import annotations

from ..errors import DataRepairError
from .model import RepairPatch, SeriesKey
from .tushare_159326 import PATCH as TUSHARE_159326
from .tushare_510500 import PATCH as TUSHARE_510500
from .tushare_512100 import PATCH as TUSHARE_512100
from .tushare_515050 import PATCH as TUSHARE_515050
from .tushare_518800 import PATCH as TUSHARE_518800
from .tushare_518880 import PATCH as TUSHARE_518880
from .tushare_588080 import PATCH as TUSHARE_588080


REPAIR_PATCHES: tuple[RepairPatch, ...] = (
    TUSHARE_159326,
    TUSHARE_510500,
    TUSHARE_512100,
    TUSHARE_515050,
    TUSHARE_518800,
    TUSHARE_518880,
    TUSHARE_588080,
)


def validate_repair_patches(
    patches: tuple[RepairPatch, ...] = REPAIR_PATCHES,
) -> None:
    patch_ids = [patch.patch_id for patch in patches]
    if len(patch_ids) != len(set(patch_ids)):
        raise DataRepairError("repair registry contains duplicate patch ids")
    targets = [(patch.vendor, patch.symbol) for patch in patches]
    if len(targets) != len(set(targets)):
        raise DataRepairError("repair registry contains duplicate vendor-symbol patches")


validate_repair_patches()


def patch_for(series: SeriesKey) -> RepairPatch | None:
    return next((patch for patch in REPAIR_PATCHES if patch.matches(series)), None)


__all__ = ["REPAIR_PATCHES", "patch_for", "validate_repair_patches"]
